"""Join the persisted supplier Operation to the same app/DBOS continuation seam."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dbos import DBOS, DBOSClient, DBOSConfig
from sqlalchemy import create_engine, text

from integrations.seam_admission import ExecutionScope, SeamAdmission
from integrations.seam_continuation import SeamContinuation
from scripts.p0.gateway_probe import Gateway, canonical_json
from scripts.p0.check_continuation import _wait_for_workflow

DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
APP = "cloudhelm-p0-a01-live-continuation"
SCHEMA = "p0_a01_live_continuation_dbos"
VERSION = "p0-a01-live-continuation-r1"
QUEUE = "p0-a01-live-continuation"


def run() -> dict:
    engine = create_engine(DSN, pool_size=3, max_overflow=0, hide_parameters=True)
    admission = SeamAdmission(engine)
    DBOS(config=DBOSConfig(
        name=APP, system_database_url=DSN, dbos_system_schema=SCHEMA,
        application_version=VERSION, executor_id="p0-a01-live-continuation-worker",
        enable_otlp=False, use_listen_notify=False, run_migrations=True,
        log_level="WARNING", console_log_level="WARNING",
    ))
    DBOS.launch()
    DBOS.register_queue(QUEUE, worker_concurrency=1)
    client = DBOSClient(system_database_engine=engine, dbos_system_schema=SCHEMA,
                        application_name=APP, retry_connection_errors=False)
    continuation = SeamContinuation(admission, client, application_name=APP,
                                    code_version=VERSION, queue_name=QUEUE)
    continuation.bootstrap()
    reports = {}
    try:
        for scenario in ("normal", "disconnect"):
            scope = ExecutionScope(f"a01-{scenario}", f"a01-session-{scenario}",
                                   f"a01-run-{scenario}", "r1", "r1", "r1")
            gateway = Gateway(f"a01-{scenario}")
            with engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT receipt,operation_id,request_digest FROM p0_protocol.operations "
                    "WHERE probe_id=:probe"
                ), {"probe": gateway.probe_id}).mappings().one()
                checkpoint = connection.execute(text(
                    "SELECT checkpoint_id FROM p0_checkpoint.context_references "
                    "WHERE history_ref=:history"
                ), {"history": f"history:a01:{scenario}:r1"}).scalar_one()
            receipt = row["receipt"]
            operation_digest = row["request_digest"].strip()
            observed = gateway.await_operation(
                operation_id=row["operation_id"], expected_digest=operation_digest,
                policy_revision=gateway.gate.revision,
            )
            assert observed is not None and observed["status"] == "completed"
            result_ref = {
                "schema": "p0_protocol.operations", "probe_id": gateway.probe_id,
                "operation_id": row["operation_id"], "result_id": "a01-result-1",
                "result_digest": hashlib.sha256(canonical_json({"counter_delta": 1}).encode()).hexdigest(),
            }
            wait = continuation.record_wait(
                scope, operation_id=row["operation_id"], operation_digest=operation_digest,
                accepted_receipt=receipt, checkpoint_ref=checkpoint,
                gateway_result_ref=result_ref,
            )
            resumed = continuation.resume_wait(scope, wait["wait_id"])
            replay = continuation.resume_wait(scope, wait["wait_id"])
            result = _wait_for_workflow(client, resumed["workflow_id"])
            resumed_scope = ExecutionScope(scope.task_id, scope.session_id, result["new_run_id"],
                                           scope.control_revision, scope.permission_revision,
                                           scope.input_revision)
            acknowledged = continuation.complete_resume(resumed_scope, wait["wait_id"], result)
            ack_replay = continuation.complete_resume(resumed_scope, wait["wait_id"], result)
            assert not ack_replay["applied"] and ack_replay["task_status"] == "active"
            evidence = continuation.evidence(wait["wait_id"])
            assert resumed["workflow_id"] == replay["workflow_id"]
            assert resumed["new_run_id"] == replay["new_run_id"] and not replay["should_enqueue"]
            assert result["new_run_id"] != scope.run_id
            facts = gateway.evidence_snapshot(policy_revision=gateway.gate.revision)
            assert facts["effects"] == facts["operations"] == facts["counter"] == 1
            reports[scenario] = {"original_run_id": scope.run_id, "new_run_id": result["new_run_id"],
                                 "workflow_id": resumed["workflow_id"], "operation_id": row["operation_id"],
                                 "facts": facts, "accepted_receipt_preserved": True,
                                 "new_supplier_requests": 0, "app_acknowledged": acknowledged,
                                 "evidence": evidence}
        return {"candidate": "SDK-A01-C1", "passed": True, "scenarios": reports}
    finally:
        client.destroy()
        DBOS.destroy()
        engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False, default=str, separators=(",", ":")))
    except Exception as exc:
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
