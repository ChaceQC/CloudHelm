"""Seal one original operation, then persist only independently observed closeout facts."""

import json
from datetime import UTC, datetime

from modules.delivery.release_recipe import delivery_digest
from packages.contracts.p0.permit_contracts import GrantAcceptance
from packages.contracts.p0.resource_contracts import ResourceVector
from packages.contracts.p1.closeout_contracts import RemoteCloseoutReceipt
from packages.contracts.p1.delivery_records import EnvironmentState
from packages.contracts.p1.remote_delivery import RemotePlan, RemoteStepResult
from . import closeout_facts, closeout_ledger
from .ledger import RemoteError
from .resources import Resources


def _facts(db, deployment):
    plan, operation = deployment.plan, deployment.operation_id
    steps_by_id = {step.step_id: step for step in plan.steps}
    grants = [dict(row) for row in db.execute("SELECT * FROM grants WHERE operation=? ORDER BY id", (operation,))]
    steps = [dict(row) for row in db.execute("SELECT * FROM steps WHERE operation=? ORDER BY step", (operation,))]
    if len(grants) > 64 or len(steps) > 1 or any(row["step"] != "artifact_prepare" for row in steps):
        raise RemoteError("remote_closeout_scope_invalid")
    accepted = {}
    for row in grants:
        acceptance = GrantAcceptance.model_validate_json(row["acceptance"])
        grant, binding = acceptance.grant, acceptance.grant.binding
        step = steps_by_id.get(row["step"])
        if (step is None or grant.grant_id != row["id"] or binding.operation_id != operation
                or binding.plan_digest != deployment.plan_digest or binding.step_id != step.step_id
                or binding.input_digest != step.input_digest or binding.executor_instance != plan.executor_instance
                or binding.generation != plan.generation or binding.environment_execution_id != operation
                or binding.environment_config_revision_id != plan.configuration.configuration.config_revision_id
                or row["closed"] not in (0, 1)):
            raise RemoteError("remote_closeout_ledger_facts_invalid")
        accepted[row["id"]] = row
    for row in steps:
        step, grant = steps_by_id.get(row["step"]), accepted.get(row["grant_id"])
        if (step is None or row["digest"] != step.input_digest or grant is None or grant["step"] != row["step"]
                or row["status"] not in {"unknown", "succeeded", "failed_known"}):
            raise RemoteError("remote_closeout_ledger_facts_invalid")
        if row["result"] is None:
            if row["status"] != "unknown":
                raise RemoteError("remote_closeout_ledger_facts_invalid")
        else:
            result = RemoteStepResult.model_validate_json(row["result"])
            if (result.operation_id != operation or result.plan_digest != deployment.plan_digest
                    or result.step_id != row["step"] or result.input_digest != row["digest"]
                    or result.grant_id != row["grant_id"] or result.status != row["status"]
                    or result.executor_instance != plan.executor_instance or result.generation != plan.generation):
                raise RemoteError("remote_closeout_ledger_facts_invalid")
    return {"operation_id": operation, "plan_digest": deployment.plan_digest, "grants": grants, "steps": steps}


def closeout(ledger, registration, operation_id, resource_config):
    row = ledger.db.execute("SELECT payload FROM operations WHERE id=?", (operation_id,)).fetchone()
    if row is None:
        raise RemoteError("remote_original_operation_missing")
    try:
        deployment = RemotePlan.model_validate_json(row[0])
    except ValueError:
        raise RemoteError("remote_original_operation_binding_invalid") from None
    plan, binding = deployment.plan, deployment.plan.binding
    with ledger.locked(binding.binding_id):
        current = ledger.db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        lineage = ledger.db.execute("SELECT installation FROM lineage").fetchall()
        if (current is None or current["payload"] != row[0] or current["id"] != deployment.operation_id
                or current["binding"] != binding.binding_id or current["digest"] != deployment.plan_digest):
            raise RemoteError("remote_original_operation_binding_invalid")
        if (len(lineage) != 1 or lineage[0][0] != binding.installation_id
                or registration.installation_id != binding.installation_id or registration.target_id != binding.target_id):
            raise RemoteError("remote_original_target_mismatch")
        if (plan.expected_state != EnvironmentState(environment_revision=0)
                or plan.expected_state_digest != delivery_digest(plan.expected_state)):
            raise RemoteError("remote_closeout_scope_invalid")
        fence = {"operation_id": operation_id, "plan_digest": deployment.plan_digest,
            "binding_id": binding.binding_id, "target_id": binding.target_id, "installation_id": binding.installation_id,
            "executor_instance": plan.executor_instance, "generation": plan.generation}
        fence_digest = delivery_digest(fence)
        try:
            with ledger.transaction():
                closeout_ledger.upgrade(ledger.db)
                ledger.schema_version = 1
                sealed = ledger.db.execute("SELECT * FROM closeouts WHERE operation=?", (operation_id,)).fetchone()
                if sealed is not None and sealed["receipt"] is not None:
                    if sealed["fence_digest"] != fence_digest or current["status"] != "closed_retained":
                        raise RemoteError("remote_closeout_ledger_facts_invalid")
                    return RemoteCloseoutReceipt.model_validate_json(sealed["receipt"])
                if current["status"] != "active":
                    raise RemoteError("remote_closeout_scope_invalid")
                baseline = ledger.db.execute("SELECT value FROM environments WHERE binding=?", (binding.binding_id,)).fetchone()
                if baseline is not None and EnvironmentState.model_validate_json(baseline[0]) != plan.expected_state:
                    raise RemoteError("remote_closeout_scope_invalid")
                _facts(ledger.db, deployment)
                ledger.db.execute("UPDATE grants SET closed=1 WHERE operation=?", (operation_id,))
                facts = _facts(ledger.db, deployment)
                facts_json = json.dumps(facts, sort_keys=True, separators=(",", ":"))
                if sealed is None:
                    ledger.db.execute("INSERT INTO closeouts(operation,fence_digest,ledger_facts) VALUES (?,?,?)",
                        (operation_id, fence_digest, facts_json))
                elif sealed["fence_digest"] != fence_digest or sealed["ledger_facts"] != facts_json:
                    raise RemoteError("remote_closeout_ledger_facts_invalid")
        except ValueError:
            raise RemoteError("remote_closeout_ledger_facts_invalid") from None

        try:
            config = dict(resource_config)
            docker_root = config.pop("closeout_docker_root")
            unit = config.pop("closeout_daemon_unit")
            resources = Resources(None, **config)
            physical = closeout_facts.collect(ledger, resources, docker_root, unit, plan.configuration.resources.disk_bytes)
        except (KeyError, TypeError, OSError, ValueError):
            raise RemoteError("remote_closeout_physical_evidence_unavailable") from None
        receipt = RemoteCloseoutReceipt(**fence, environment_revision=1, fence_digest=fence_digest,
            ledger_facts_digest=delivery_digest(facts), physical_evidence_digest=delivery_digest(physical),
            closed_grant_ids=tuple(row["id"] for row in facts["grants"]),
            started_step_ids=tuple(row["step"] for row in facts["steps"]),
            retained_resources=ResourceVector(disk_bytes=plan.configuration.resources.disk_bytes), observed_at=datetime.now(UTC))
        with ledger.transaction():
            ledger.db.execute("UPDATE closeouts SET physical_evidence=?,receipt=? WHERE operation=?",
                (json.dumps(physical, sort_keys=True, separators=(",", ":")), receipt.model_dump_json(), operation_id))
            state = EnvironmentState(environment_revision=receipt.environment_revision)
            ledger.db.execute("INSERT INTO environments(binding,value) VALUES (?,?) "
                "ON CONFLICT(binding) DO UPDATE SET value=excluded.value", (binding.binding_id, state.model_dump_json()))
            ledger.db.execute("UPDATE operations SET status='closed_retained' WHERE id=?", (operation_id,))
        return receipt
