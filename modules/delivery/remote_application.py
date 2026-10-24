"""Hub-side authenticated exchange; the Remote Agent alone chooses the next step."""

from sqlalchemy import func, select, update

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_control import approved_preflight
from modules.delivery.deployment_store import lock_binding
from modules.delivery.deployment_tables import deployment_approvals, environment_bindings
from modules.delivery.permit_clock import PermitClock
from modules.delivery.release_recipe import delivery_digest
from modules.delivery.remote_auth import authenticate_remote
from modules.delivery.remote_permits import issue_permit
from modules.delivery.remote_store import approved_operation, package_plan, save_projection, step_results
from modules.delivery.remote_tables import remote_grants, remote_results, remote_samples
from modules.delivery.target_facts import (
    collect_target_observation, read_target, register_observation,
)
from modules.sync.events import append_event
from modules.sync.tables import event_log
from packages.contracts.p1.remote_delivery import RemoteBindings, RemotePollResult, RemoteTimeSample


class _ChannelProducer:
    def __init__(self, observation):
        self.observation = observation

    def read_observation(self, binding):
        return self.observation


class RemoteApplication:
    def __init__(self, engine, *, clock=None, artifact_store=None):
        self.engine = engine
        self.clock = clock if clock is not None else PermitClock()
        self.artifact_store = artifact_store

    def bindings(self, token, request):
        from packages.contracts.p1.delivery_records import EnvironmentBinding

        with UnitOfWork(self.engine) as uow:
            credential = authenticate_remote(uow, token)
            target = read_target(uow.connection, credential["project_id"], credential["target_id"], credential["installation_id"])
            if request.executor_instance != target.executor_instance or request.generation != target.generation:
                raise TaskBoundaryError("remote_executor_stale")
            rows = uow.connection.execute(select(environment_bindings.c.value_json).where(
                environment_bindings.c.project_id == credential["project_id"],
                environment_bindings.c.value_json["target_id"].astext == credential["target_id"],
                environment_bindings.c.value_json["installation_id"].astext == credential["installation_id"],
            ).limit(17)).scalars().all()
            if len(rows) > 16:
                raise TaskBoundaryError("remote_bindings_scope_exceeded")
            return RemoteBindings(bindings=tuple(EnvironmentBinding.model_validate(row) for row in rows))

    def sample(self, token, hello):
        with UnitOfWork(self.engine) as uow:
            credential = authenticate_remote(uow, token)
            target = read_target(uow.connection, credential["project_id"], credential["target_id"], credential["installation_id"])
            if hello.executor_instance != target.executor_instance or hello.generation != target.generation:
                raise TaskBoundaryError("remote_executor_stale")
            key = "sample-" + delivery_digest({"credential": credential["credential_id"], "nonce": hello.sample_nonce})[7:]
            previous = uow.connection.scalar(select(remote_samples.c.value_json).where(remote_samples.c.id == key))
            if previous is not None:
                value = RemoteTimeSample.model_validate(previous)
                if value.hello != hello:
                    raise TaskBoundaryError("remote_sample_nonce_rebound")
                return value
            value = self.clock.sample(hello, "channel-" + credential["credential_id"])
            save_projection(uow.connection, remote_samples, credential, key, value)
            return value

    def poll(self, token, request):
        with UnitOfWork(self.engine) as uow:
            credential = authenticate_remote(uow, token)
            rows = uow.connection.execute(select(deployment_approvals.c.value_json["operation_id"].astext).where(
                deployment_approvals.c.project_id == credential["project_id"],
            ).order_by(deployment_approvals.c.created_at).limit(129)).scalars().all()
            if len(rows) > 128:
                raise TaskBoundaryError("remote_plan_scope_exceeded")
            blocked = None
            for operation in rows:
                try:
                    context, plan, approval = approved_operation(uow, credential, operation)
                    if (plan.value.executor_instance != request.executor_instance or plan.value.generation != request.generation):
                        continue
                    row, _ = lock_binding(uow.connection, context.project_id, plan.value.binding.binding_id)
                    results = step_results(uow.connection, operation)
                    if any(value.status in {"unknown", "failed_known"} for value in results.values()):
                        blocked = "remote_original_execution_needs_reconciliation"
                        continue
                    if all(step.step_id in results and results[step.step_id].status == "succeeded" for step in plan.value.steps):
                        continue
                    if row["active_operation_id"] != operation:
                        approved_preflight(context, plan.object_id, plan.digest)
                    return RemotePollResult(status="ready", code="original_operation", deployment=package_plan(uow.connection, plan, approval))
                except TaskBoundaryError as error:
                    if error.code != "remote_target_scope_mismatch":
                        blocked = error.code
            if blocked is not None:
                return RemotePollResult(status="waiting_authorization", code=blocked)
            return RemotePollResult(status="idle", code="no_pending_plan")

    def observe(self, token, request):
        with UnitOfWork(self.engine) as uow:
            credential = authenticate_remote(uow, token)
            value = request.observation
            if value.target_id != credential["target_id"] or value.installation_id != credential["installation_id"]:
                raise TaskBoundaryError("remote_target_scope_mismatch", status_code=403)
            now = uow.connection.scalar(select(func.clock_timestamp()))
            if not 0 <= (now - value.observed_at).total_seconds() < 60:
                raise TaskBoundaryError("remote_observation_stale")
            return {"digest": register_observation(uow, credential["project_id"],
                collect_target_observation(_ChannelProducer(value), value))}

    def permit(self, token, request):
        with UnitOfWork(self.engine) as uow:
            return issue_permit(uow, authenticate_remote(uow, token), request, self.clock)

    def report(self, token, result):
        with UnitOfWork(self.engine) as uow:
            credential = authenticate_remote(uow, token)
            context, plan, approval = approved_operation(uow, credential, result.operation_id)
            row, binding = lock_binding(uow.connection, context.project_id, plan.value.binding.binding_id)
            grant = uow.connection.execute(select(remote_grants).where(
                remote_grants.c.id == result.grant_id, remote_grants.c.credential_id == credential["credential_id"],
                remote_grants.c.operation_id == result.operation_id, remote_grants.c.step_id == result.step_id,
            )).mappings().one_or_none()
            if grant is None or row["active_operation_id"] not in (None, result.operation_id):
                raise TaskBoundaryError("remote_result_unbound")
            validate_result(plan, result, grant["value_json"]["permit"]["grant"])
            key = "result-" + delivery_digest(result)[7:]
            save_projection(uow.connection, remote_results, credential, key, result, result.operation_id, result.step_id)
            if uow.connection.scalar(select(event_log.c.event_id).where(event_log.c.event_id == key)) is None:
                append_event(uow.connection, command_id=context.envelope.command_id, project_id=context.project_id,
                    aggregate_kind="deployment", aggregate_id=result.operation_id,
                    aggregate_version=next(index + 1 for index, step in enumerate(plan.value.steps) if step.step_id == result.step_id),
                    event_type="deployment.step_observed", schema_version="p1-remote-step-r1", payload=result, event_id=key)
            results = step_results(uow.connection, result.operation_id)
            if all(step.step_id in results and results[step.step_id].status == "succeeded" for step in plan.value.steps):
                uow.connection.execute(update(environment_bindings).where(
                    environment_bindings.c.binding_id == binding.binding_id,
                    environment_bindings.c.active_operation_id == result.operation_id,
                ).values(active_operation_id=None))
            return {"digest": delivery_digest(result), "status": result.status}

    def open_artifact(self, token, operation, storage_id):
        if self.artifact_store is None:
            raise TaskBoundaryError("remote_artifact_store_unavailable", status_code=503)
        with UnitOfWork(self.engine) as uow:
            credential = authenticate_remote(uow, token)
            _, plan, approval = approved_operation(uow, credential, operation)
            deployment = package_plan(uow.connection, plan, approval)
            if storage_id not in {item.storage_id for item in deployment.manifest.artifacts}:
                raise TaskBoundaryError("remote_artifact_not_in_plan", status_code=403)
        # The verified inode remains open and locked throughout the HTTP stream.
        return self.artifact_store.open_archive(storage_id)


def validate_result(plan, result, grant):
    step = next((s for s in plan.value.steps if s.step_id == result.step_id), None)
    if (step is None or result.plan_digest != plan.digest or result.input_digest != step.input_digest
            or result.executor_instance != plan.value.executor_instance or result.generation != plan.value.generation
            or grant["binding"]["plan_digest"] != result.plan_digest
            or grant["binding"]["input_digest"] != result.input_digest):
        raise TaskBoundaryError("remote_result_binding_invalid")
    if result.status != "succeeded":
        return
    if result.state.unregistered_resources:
        raise TaskBoundaryError("remote_result_unreconciled_resources")
    if step.kind == "database_migrate" and (
        result.database_operation_id != result.operation_id or result.database_input_digest != step.input_digest
        or set(result.database_postchecks) != {"schema_integrity", "data_integrity", "application_probe"}
        or result.state.database_revision != "0002_add_updated_at_index"
    ):
        raise TaskBoundaryError("remote_database_evidence_incomplete")
    if step.kind == "health_verify":
        if (result.health_started_at is None or result.health_finished_at is None or result.health_samples < 2
                or (result.health_finished_at - result.health_started_at).total_seconds() < plan.value.health_window_seconds
                or result.observed_at < result.health_finished_at
                or result.state.environment_revision != plan.value.expected_state.environment_revision + 1
                or result.state.release_id != plan.value.release_id
                or result.state.config_revision_id != plan.value.configuration.configuration.config_revision_id
                or result.state.database_revision != "0002_add_updated_at_index"
                or set(result.state.services) != {"postgres", "backend", "frontend"}
                or any(service.state != "running" for service in result.state.services.values())):
            raise TaskBoundaryError("remote_health_window_incomplete")
        inputs = plan.value.step_inputs["service_update"]
        for role, service in result.state.services.items():
            if (service.loaded_image_id != inputs["expected_loaded_image_ids"][role]
                    or service.config_digest != inputs["expected_config_digests"][role]
                    or service.docker_identity_kind != plan.value.docker_identity_kind):
                raise TaskBoundaryError("remote_service_identity_mismatch")
