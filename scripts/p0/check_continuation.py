"""One isolated Gateway -> wait -> DBOS transactional continuation check."""

from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from dbos import DBOS, DBOSClient, DBOSConfig
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.seam_admission import ExecutionScope, GateDenied, SeamAdmission
from integrations.seam_checkpoint import CheckpointStore, ContextReferences
from integrations.seam_continuation import (
    ContinuationConflict,
    InjectedContinuationFailure,
    SeamContinuation,
    WORKFLOW_NAME,
)
from scripts.p0.gateway_probe import (
    CurrentGate,
    Gateway,
    canonical_json,
)

SYNC_DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
DBOS_SCHEMA = "p0_a01_continuation_dbos"
APP_NAME = "cloudhelm-p0-a01-continuation"
APP_VERSION = "p0.1-a01b-continuation-r1"
_QUEUE_BASE = "p0-a01-continuation"
_ACTIVE_PHASE = "initializing"


def _scope(prefix: str) -> ExecutionScope:
    return ExecutionScope(
        task_id=f"{prefix}-task",
        session_id=f"{prefix}-session",
        run_id=f"{prefix}-run-old",
        control_revision="1",
        permission_revision="1",
        input_revision="1",
    )


def _expect_gate_denied(action: Callable[[], object]) -> None:
    try:
        action()
    except GateDenied:
        return
    raise AssertionError("current authority accepted a blocked continuation")


def _expect_conflict(action: Callable[[], object]) -> None:
    try:
        action()
    except ContinuationConflict:
        return
    raise AssertionError("continuation accepted a different digest for a stable identity")


def _wait_for_workflow(client: DBOSClient, workflow_id: str, timeout: float = 15) -> Any:
    handle = client.retrieve_workflow(workflow_id)
    deadline = time.monotonic() + timeout
    while True:
        status = handle.get_status()
        if status.status == "SUCCESS":
            return handle.get_result(polling_interval_sec=0.05)
        if status.status in {"ERROR", "MAX_RECOVERY_ATTEMPTS_EXCEEDED", "CANCELLED"}:
            raise AssertionError("public DBOS workflow ended unsuccessfully")
        if time.monotonic() >= deadline:
            raise TimeoutError("public DBOS workflow did not finish before the check deadline")
        time.sleep(0.05)


def _reference_from_gateway(
    gateway: Gateway,
    *,
    operation_id: str,
    operation_digest: str,
    result_id: str,
    supplied_result: dict[str, Any],
) -> dict[str, str]:
    observed = gateway.await_operation(
        operation_id=operation_id,
        expected_digest=operation_digest,
        policy_revision=gateway.gate.revision,
    )
    expected_digest = hashlib.sha256(canonical_json(supplied_result).encode("utf-8")).hexdigest()
    if (
        observed is None
        or observed.get("status") != "completed"
        or observed.get("operation_id") != operation_id
        or observed.get("result_id") != result_id
        or observed.get("counter") != 1
    ):
        raise AssertionError("Gateway query did not return the fixed completed Operation")
    return {
        "schema": "p0_protocol.operations",
        "probe_id": gateway.probe_id,
        "operation_id": operation_id,
        "result_id": result_id,
        "result_digest": expected_digest,
    }


def main() -> int:
    run_token = uuid.uuid4().hex[:16]
    gateway_probe_id = f"a01-cont-{run_token}"
    queue_name = f"{_QUEUE_BASE}-{run_token}"
    scope = _scope(f"a01-cont-{run_token}")
    engine = create_engine(
        SYNC_DSN,
        pool_size=4,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"application_name": "cloudhelm_a01_continuation_probe"},
    )
    admission = SeamAdmission(engine)
    checkpoint_store = CheckpointStore(engine)
    runtime_started = False
    client: DBOSClient | None = None
    try:
        global _ACTIVE_PHASE
        _ACTIVE_PHASE = "isolated app schema bootstrap"
        admission.bootstrap()
        continuation = None
        refs = ContextReferences(
            requirement_ref=f"requirement://{run_token}",
            input_set_ref=f"input-set://{run_token}",
            history_ref=f"history-ref://{run_token}",
            artifact_ref=f"artifact-ref://{run_token}",
            secret_resource_ref=f"secret-ref://{run_token}",
        )
        checkpoint_store.bootstrap()
        checkpoint_ref = checkpoint_store.put(refs)

        admission.seed_scope(scope, Decimal("1"))
        with engine.connect() as connection:
            postgresql_version = connection.execute(
                text("SELECT current_setting('server_version')")
            ).scalar_one()

        _ACTIVE_PHASE = "Gateway accepted and completed Operation"
        gateway = Gateway(probe_id=gateway_probe_id, gate=CurrentGate())
        Gateway.prepare()
        receipt, accepted_new = gateway.submit_operation(
            idempotency_key=f"{run_token}-counter-effect",
            tool_call_id=f"tool-call-{run_token}",
            args={"counter_delta": 1, "kind": "single counter effect"},
            policy_revision=gateway.gate.revision,
        )
        if not accepted_new or receipt["status"] != "accepted":
            raise AssertionError("Gateway did not persist a fresh accepted receipt")
        operation_id = receipt["operation_id"]
        operation_digest = receipt["request_digest"]
        result_id = f"result-{run_token}"
        result_body = {"counter_delta": 1, "outcome_ref": f"result-ref://{run_token}"}
        completed, applied = gateway.complete_operation(
            operation_id=operation_id,
            expected_digest=operation_digest,
            result_id=result_id,
            result=result_body,
            policy_revision=gateway.gate.revision,
        )
        if not applied or completed["counter"] != 1:
            raise AssertionError("Gateway did not apply the single counter effect")
        repeated_result, repeated_applied = gateway.complete_operation(
            operation_id=operation_id,
            expected_digest=operation_digest,
            result_id=result_id,
            result=result_body,
            policy_revision=gateway.gate.revision,
        )
        if repeated_applied or repeated_result != completed:
            raise AssertionError("Gateway result replay changed the completed Operation")
        gateway_result_ref = _reference_from_gateway(
            gateway,
            operation_id=operation_id,
            operation_digest=operation_digest,
            result_id=result_id,
            supplied_result=result_body,
        )

        _ACTIVE_PHASE = "DBOS runtime and continuation schema bootstrap"
        DBOS(
            config=DBOSConfig(
                name=APP_NAME,
                system_database_url=SYNC_DSN,
                dbos_system_schema=DBOS_SCHEMA,
                application_version=APP_VERSION,
                executor_id=f"a01-cont-{run_token}",
                enable_otlp=False,
                use_listen_notify=False,
                run_migrations=True,
                log_level="WARNING",
                console_log_level="WARNING",
            )
        )
        DBOS.launch()
        runtime_started = True
        DBOS.register_queue(queue_name, worker_concurrency=1)
        client = DBOSClient(
            system_database_engine=engine,
            dbos_system_schema=DBOS_SCHEMA,
            application_name=APP_NAME,
            retry_connection_errors=False,
        )
        continuation = SeamContinuation(
            admission,
            client,
            application_name=APP_NAME,
            code_version=APP_VERSION,
            queue_name=queue_name,
        )
        continuation.bootstrap()

        _ACTIVE_PHASE = "wait receipt and completed Gateway reference persistence"
        wait = continuation.record_wait(
            scope,
            operation_id=operation_id,
            operation_digest=operation_digest,
            accepted_receipt=receipt,
            checkpoint_ref=checkpoint_ref,
            gateway_result_ref=gateway_result_ref,
        )
        if (
            wait["outcome"] != "waiting_condition"
            or wait["status"] != "ready"
            or wait["accepted_receipt"] != receipt
            or wait["original_run_id"] != scope.run_id
        ):
            raise AssertionError("wait did not preserve the original accepted receipt and Run")
        wait_id = wait["wait_id"]
        different_digest = hashlib.sha256(b"different Operation digest").hexdigest()
        different_receipt = {**receipt, "request_digest": different_digest}
        _expect_conflict(
            lambda: continuation.record_wait(
                scope,
                operation_id=operation_id,
                operation_digest=different_digest,
                accepted_receipt=different_receipt,
                checkpoint_ref=checkpoint_ref,
                wait_id=wait_id,
            )
        )
        _expect_conflict(
            lambda: continuation.observe_result(
                wait_id,
                {**gateway_result_ref, "result_id": f"different-{run_token}"},
            )
        )

        _ACTIVE_PHASE = "cancel, revoke, and stale revision gates"
        cancel_scope = _scope(f"a01-cont-{run_token}-cancel")
        revoke_scope = _scope(f"a01-cont-{run_token}-revoke")
        revision_scope = _scope(f"a01-cont-{run_token}-revision")
        for fixture_scope in (cancel_scope, revoke_scope, revision_scope):
            admission.seed_scope(fixture_scope, Decimal("1"))
            continuation.record_wait(
                fixture_scope,
                operation_id=operation_id,
                operation_digest=operation_digest,
                accepted_receipt=receipt,
                checkpoint_ref=checkpoint_ref,
                gateway_result_ref=gateway_result_ref,
            )
        cancel_wait_id = continuation.record_wait(
            cancel_scope,
            operation_id=operation_id,
            operation_digest=operation_digest,
            accepted_receipt=receipt,
            checkpoint_ref=checkpoint_ref,
            gateway_result_ref=gateway_result_ref,
        )["wait_id"]
        cancelled = admission.change_scope(cancel_scope, cancel_requested=True)
        _expect_gate_denied(lambda: continuation.resume_wait(cancel_scope, cancel_wait_id))
        _expect_gate_denied(lambda: continuation.resume_wait(cancelled, cancel_wait_id))

        revoke_wait_id = continuation.record_wait(
            revoke_scope,
            operation_id=operation_id,
            operation_digest=operation_digest,
            accepted_receipt=receipt,
            checkpoint_ref=checkpoint_ref,
            gateway_result_ref=gateway_result_ref,
        )["wait_id"]
        revoked = admission.change_scope(revoke_scope, permitted=False)
        _expect_gate_denied(lambda: continuation.resume_wait(revoke_scope, revoke_wait_id))
        _expect_gate_denied(lambda: continuation.resume_wait(revoked, revoke_wait_id))

        revision_wait_id = continuation.record_wait(
            revision_scope,
            operation_id=operation_id,
            operation_digest=operation_digest,
            accepted_receipt=receipt,
            checkpoint_ref=checkpoint_ref,
            gateway_result_ref=gateway_result_ref,
        )["wait_id"]
        changed_revision = admission.change_scope(
            revision_scope, input_revision="2", input_valid=False
        )
        _expect_gate_denied(
            lambda: continuation.resume_wait(revision_scope, revision_wait_id)
        )
        _expect_gate_denied(
            lambda: continuation.resume_wait(changed_revision, revision_wait_id)
        )

        _ACTIVE_PHASE = "enqueue rollback and public DBOS absence check"
        # All state and the DBOS workflow insertion must roll back together.
        _expect_injected_rollback = False
        try:
            continuation.resume_wait(scope, wait_id, fail_at="enqueue")
        except InjectedContinuationFailure:
            _expect_injected_rollback = True
        if not _expect_injected_rollback:
            raise AssertionError("enqueue failure injection did not fire")
        rolled_back = continuation.evidence(wait_id)
        if (
            rolled_back["wait"]["status"] != "ready"
            or rolled_back["wait"]["new_run_id"] is not None
            or rolled_back["session_status"] != "waiting"
            or len(rolled_back["runs"]) != 1
            or rolled_back["event_count"] != 2
            or rolled_back["workflow_binding"] is not None
            or client.list_workflows(
                workflow_ids=["wf-" + hashlib.sha256(
                    "\0".join((wait_id, _resume_digest_from_wait(rolled_back["wait"]))).encode("utf-8")
                ).hexdigest()[:48]],
                load_input=True,
                load_output=True,
                limit=1,
            )
        ):
            raise AssertionError("enqueue failure did not roll back continuation state")

        _ACTIVE_PHASE = "continuation resume, wait replay, and public workflow result"
        resumed = continuation.resume_wait(scope, wait_id)
        if not resumed["should_enqueue"]:
            raise AssertionError("first continuation resume did not enqueue a new workflow")
        evidence = continuation.evidence(wait_id)
        workflow_id = resumed["workflow_id"]
        new_run_id = resumed["new_run_id"]
        if (
            new_run_id == scope.run_id
            or evidence["session_status"] != "running"
            or evidence["current_run_id"] != new_run_id
            or evidence["event_count"] != 3
            or evidence["workflow_binding"]["run_id"] != new_run_id
        ):
            raise AssertionError("resume did not create one distinct current Run and binding")
        replayed = continuation.resume_wait(scope, wait_id)
        if (
            replayed["should_enqueue"]
            or replayed["new_run_id"] != new_run_id
            or replayed["workflow_id"] != workflow_id
        ):
            raise AssertionError("resume replay did not return the original new Run/workflow")
        workflow_result = _wait_for_workflow(client, workflow_id)
        workflow_result_again = client.retrieve_workflow(workflow_id).get_result(
            polling_interval_sec=0.05
        )
        if workflow_result != workflow_result_again:
            raise AssertionError("retrieving the same workflow changed its result")
        if (
            workflow_result["new_run_id"] != new_run_id
            or workflow_result["operation_id"] != operation_id
            or workflow_result["checkpoint_ref"] != checkpoint_ref
        ):
            raise AssertionError("DBOS continuation result did not preserve the safe references")

        _ACTIVE_PHASE = "app-owned Run result acknowledgment"
        resumed_scope = ExecutionScope(
            task_id=scope.task_id,
            session_id=scope.session_id,
            run_id=new_run_id,
            control_revision=scope.control_revision,
            permission_revision=scope.permission_revision,
            input_revision=scope.input_revision,
        )
        _expect_gate_denied(
            lambda: continuation.complete_resume(scope, wait_id, workflow_result)
        )
        acknowledged = continuation.complete_resume(
            resumed_scope, wait_id, workflow_result
        )
        if (
            not acknowledged["applied"]
            or acknowledged["run_status"] != "succeeded"
            or acknowledged["run_outcome"] != "continue_required"
            or acknowledged["session_status"] != "idle"
            or acknowledged["task_status"] != "active"
        ):
            raise AssertionError("application did not acknowledge the current Run safely")
        replayed_ack = continuation.complete_resume(
            resumed_scope, wait_id, workflow_result
        )
        if replayed_ack["applied"] or replayed_ack != acknowledged | {"applied": False}:
            raise AssertionError("acknowledgment replay changed the saved Run result")
        acknowledged_evidence = continuation.evidence(wait_id)
        active_run_count = sum(
            run["status"] in {"queued", "running"}
            for run in acknowledged_evidence["runs"]
        )
        with engine.connect() as connection:
            authority = connection.execute(
                text(
                    """
                    SELECT task_status, session_status, run_status, run_id
                    FROM p0_admission.task_authority WHERE task_id=:task_id
                    """
                ),
                {"task_id": scope.task_id},
            ).mappings().one()
        if (
            acknowledged_evidence["wait"]["status"] != "acknowledged"
            or acknowledged_evidence["wait"]["accepted_receipt"] != receipt
            or acknowledged_evidence["session_status"] != "idle"
            or acknowledged_evidence["current_run_id"] != new_run_id
            or acknowledged_evidence["event_count"] != 4
            or active_run_count != 0
            or authority["run_id"] != new_run_id
            or authority["run_status"] != "succeeded"
            or authority["session_status"] != "idle"
            or authority["task_status"] != "active"
        ):
            raise AssertionError("app state and admission authority did not converge on the Run result")

        _ACTIVE_PHASE = "final Gateway effect count"
        gateway_counts = gateway.query_counter(policy_revision=gateway.gate.revision)
        if gateway_counts != {"counter": 1, "operations": 1, "effects": 1}:
            raise AssertionError("Gateway did not retain exactly one Operation and effect")
        print(
            json.dumps(
                {
                    "check": "p0.1-A01b continuation",
                    "result": "passed",
                    "postgresql": postgresql_version,
                    "app_schema": "p0_continuation",
                    "dbos_schema": DBOS_SCHEMA,
                    "gateway": gateway_counts,
                    "original_run": {"status": "succeeded", "outcome": "waiting_condition"},
                    "new_run_created_once": new_run_id != scope.run_id,
                    "app_run_acknowledged": True,
                    "authority_run_matches": True,
                    "task_remains_active": authority["task_status"] == "active",
                    "enqueue_failure_rolled_back": True,
                    "different_digest_rejected": True,
                    "cancel_revoke_stale_revision_rejected": True,
                    "same_workflow_result_retrieved_twice": True,
                    "workflow_status": "SUCCESS",
                    "safe_result_fields": sorted(workflow_result),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    finally:
        if client is not None:
            client.destroy()
        if runtime_started:
            DBOS.destroy()
        engine.dispose()


def _resume_digest_from_wait(wait: dict[str, Any]) -> str:
    result_ref = wait["result_ref"]
    document = {
        "wait_id": wait["wait_id"],
        "wait_digest": wait["wait_digest"],
        "result_ref": result_ref,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "check": "p0.1-A01b continuation",
                    "result": "failed",
                    "phase": _ACTIVE_PHASE,
                    "error_type": type(exc).__name__,
                    "details": "suppressed",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
