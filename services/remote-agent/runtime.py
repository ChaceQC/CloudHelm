"""Exactly one finite local progression; durable intent is never an automatic retry."""

from datetime import UTC, datetime
from uuid import uuid4

from modules.delivery.release_recipe import delivery_digest
from packages.contracts.p0.permit_contracts import PermitGate, accept_grant, check_start
from packages.contracts.p1.delivery_records import TargetObservation
from packages.contracts.p1.remote_delivery import RemotePermitRequest, RemoteStepResult
from packages.contracts.p1.remote_delivery import RemotePlan
from .ledger import RemoteError


class Agent:
    def __init__(self, ledger, channel, clock, backend, registration):
        self.ledger, self.channel, self.clock = ledger, channel, clock
        self.backend, self.registration = backend, registration

    def run_once(self):
        target = self.registration
        for binding in self.channel.bindings(target.executor_instance, target.generation).bindings:
            state = self.backend.observe_binding(binding)
            self.channel.observe(TargetObservation(observation_id="remote-observation-" + uuid4().hex,
                binding_id=binding.binding_id, target_id=target.target_id, installation_id=target.installation_id,
                executor_instance=target.executor_instance, generation=target.generation,
                reconciled=not bool(state.unregistered_resources), state=state,
                available_secret_refs=self.backend.available_secret_refs(), observed_at=datetime.now(UTC)))
        result = self.channel.poll(target.executor_instance, target.generation)
        return result.code if result.deployment is None else self.advance(result.deployment)

    def observe(self, deployment):
        plan, target = deployment.plan, self.registration
        state = self.backend.observe(deployment)
        return TargetObservation(observation_id="remote-observation-" + uuid4().hex,
            binding_id=plan.binding.binding_id, target_id=target.target_id, installation_id=target.installation_id,
            executor_instance=target.executor_instance, generation=target.generation,
            reconciled=not bool(state.unregistered_resources), state=state,
            available_secret_refs=self.backend.available_secret_refs(), observed_at=datetime.now(UTC))

    def advance(self, deployment):
        self.ledger.require_open(deployment.operation_id)
        plan = deployment.plan
        if (plan.executor_instance != self.registration.executor_instance or plan.generation != self.registration.generation
                or plan.binding.installation_id != self.registration.installation_id
                or plan.binding.target_id != self.registration.target_id):
            raise RemoteError("remote_plan_executor_mismatch")
        self.backend.validate(deployment)
        with self.ledger.locked(plan.binding.binding_id):
            self.ledger.receive(deployment)
            for step in plan.steps:
                if existing := self.ledger.step(deployment.operation_id, step.step_id):
                    result = self._original(deployment, step, existing)
                else:
                    result = self._new_step(deployment, step)
                self.channel.report(result)
                if result.status != "succeeded":
                    return "needs_reconciliation"
            self.ledger.complete(deployment, result.state)
            return "succeeded"

    def reconcile(self, operation_id):
        row = self.ledger.db.execute("SELECT payload FROM operations WHERE id=?", (operation_id,)).fetchone()
        if row is None:
            raise RemoteError("remote_original_operation_missing")
        deployment = RemotePlan.model_validate_json(row[0])
        with self.ledger.locked(deployment.plan.binding.binding_id):
            self.ledger.require_open(operation_id)
            current = self.ledger.db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            lineage = self.ledger.db.execute("SELECT installation FROM lineage").fetchall()
            binding, target = deployment.plan.binding, self.registration
            if (current is None or current["payload"] != row[0] or deployment.operation_id != operation_id
                    or current["binding"] != binding.binding_id or current["digest"] != deployment.plan_digest):
                raise RemoteError("remote_original_operation_binding_invalid")
            if (len(lineage) != 1 or lineage[0][0] != binding.installation_id
                    or target.installation_id != binding.installation_id or target.target_id != binding.target_id):
                raise RemoteError("remote_original_target_mismatch")
            # A completed operation may be replayed after a newer deployment on the same binding.
            if current["status"] == "succeeded":
                return "succeeded"
            self.backend.current = deployment
            for step in deployment.plan.steps:
                existing = self.ledger.step(operation_id, step.step_id)
                if existing is None:
                    return "original_facts_reported_no_new_step"
                try:
                    result = self._original(deployment, step, existing)
                    stored = self.ledger.step(operation_id, step.step_id)
                    if (result.operation_id != operation_id or result.plan_digest != deployment.plan_digest
                            or result.step_id != step.step_id or result.input_digest != step.input_digest
                            or result.grant_id != existing["grant_id"] or stored["status"] != result.status
                            or result.executor_instance != deployment.plan.executor_instance
                            or result.generation != deployment.plan.generation):
                        raise RemoteError("remote_result_binding_invalid")
                    self.channel.report(result)
                except Exception:
                    return "needs_reconciliation"
                if result.status != "succeeded":
                    return "needs_reconciliation"
            self.ledger.complete(deployment, result.state)
            return "succeeded"

    def _original(self, deployment, step, existing):
        if existing["digest"] != step.input_digest:
            raise RemoteError("remote_step_digest_conflict")
        saved = None if existing["result"] is None else RemoteStepResult.model_validate_json(existing["result"])
        if saved is not None and saved.status != "unknown":
            return saved
        # A crash, lost receipt or ambiguous daemon response is queried, never re-executed.
        outcome = self.backend.query(deployment, step)
        result = self._result(deployment, step, existing["grant_id"], outcome)
        if saved is not None and result.model_dump(exclude={"observed_at"}) == saved.model_dump(exclude={"observed_at"}):
            return saved
        self.ledger.finish(result)
        return result

    def _new_step(self, deployment, step):
        self.ledger.close_unstarted(deployment.operation_id, step.step_id)
        observation = self.observe(deployment)
        self.channel.observe(observation)
        mapping = self.clock.sample(self.channel, self.registration.executor_instance, self.registration.generation)
        closed = tuple(row[0] for row in self.ledger.db.execute(
            "SELECT id FROM grants WHERE operation=? AND step=? AND closed=1",
            (deployment.operation_id, step.step_id)))
        request = RemotePermitRequest(operation_id=deployment.operation_id, plan_digest=deployment.plan_digest,
            step_id=step.step_id, mapping=mapping, actual_state_digest=delivery_digest(observation.state),
            predecessor_results_digest=delivery_digest(self.ledger.results(deployment.operation_id)), closed_unstarted_grants=closed)
        permission = self.channel.permit(request)
        grant = permission.grant
        self._check_binding(deployment, step, grant, request)
        # The sample may predate issuance; a fresh sample moves the full lower bound beyond it.
        mapping = self.clock.sample(self.channel, self.registration.executor_instance, self.registration.generation)
        gate = self._gate(grant, mapping)
        acceptance = accept_grant(grant, mapping, gate)
        self.ledger.accept(deployment.operation_id, step.step_id, acceptance)
        self.backend.check_current(deployment)
        check_start(acceptance, mapping, self._gate(grant, mapping))
        self.ledger.intent(deployment.operation_id, step.step_id, step.input_digest, grant.grant_id)
        try:
            # Recheck after the durable fsync; it cannot silently consume the start window.
            check_start(acceptance, mapping, self._gate(grant, mapping))
            outcome = self.backend.execute(deployment, step, permission.environment_revision)
        except Exception:
            outcome = self.backend.query(deployment, step)
        result = self._result(deployment, step, grant.grant_id, outcome)
        self.ledger.finish(result)
        return result

    def _check_binding(self, deployment, step, grant, request):
        binding = grant.binding
        if (binding.operation_id != deployment.operation_id or binding.plan_digest != deployment.plan_digest
                or binding.step_id != step.step_id or binding.input_digest != step.input_digest
                or binding.executor_instance != self.registration.executor_instance
                or binding.generation != self.registration.generation
                or binding.environment_execution_id != deployment.operation_id
                or binding.environment_config_revision_id != deployment.plan.configuration.configuration.config_revision_id
                or binding.actual_state_digest != request.actual_state_digest
                or binding.predecessor_results_digest != request.predecessor_results_digest):
            raise RemoteError("remote_grant_binding_invalid")

    def _gate(self, grant, mapping):
        self.backend.check_local_gate()
        return PermitGate(binding=grant.binding, time_epoch=mapping.time_epoch, mapping_epoch=mapping.mapping_epoch,
            clock_continuity_id=self.clock.continuity, channel_binding_id=mapping.channel_binding_id,
            verified_time_evidence_digest=self.clock.support.evidence_digest, now_mono_us=self.clock.now(),
            authenticated=True, obtained_online=True, time_evidence_valid=True, authorized=True,
            prerequisites_met=True, resources_reserved=True, step_known_unstarted=True, other_grants_closed=True,
            maintenance_active=False)

    def _result(self, deployment, step, grant_id, outcome):
        state = self.backend.observe(deployment)
        allowed = {"database_operation_id", "database_input_digest", "database_postchecks",
                   "health_started_at", "health_finished_at", "health_samples"}
        return RemoteStepResult(operation_id=deployment.operation_id, plan_digest=deployment.plan_digest,
            step_id=step.step_id, input_digest=step.input_digest, grant_id=grant_id,
            executor_instance=deployment.plan.executor_instance, generation=deployment.plan.generation,
            status=outcome.get("status", "unknown"), state=state, evidence_digest=delivery_digest(outcome),
            observed_at=datetime.now(UTC), **{key: value for key, value in outcome.items() if key in allowed})
