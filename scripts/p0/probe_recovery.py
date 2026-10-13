"""Repeatable, local-only SDK-05/06 recovery and capacity boundary probe."""

from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from dbos import DBOS, DBOSClient, EnqueueOptions

import recovery_workflows

BUSINESS_SCHEMA = recovery_workflows.BUSINESS_SCHEMA


DEFAULT_DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
SYSTEM_SCHEMA = "dbos_p0_recovery"
APP_NAME = "cloudhelm-p0-recovery-probe"
DSN_ENV = "CLOUDHELM_P0_DSN"
APP_VERSION_ENV = "CLOUDHELM_P0_APP_VERSION"
PARAMETER_CANARY = "P0-SYNTHETIC-NONCREDENTIAL-INPUT-CANARY"
ERROR_CANARY = "P0-SYNTHETIC-NONCREDENTIAL-ERROR-CANARY"
SECRET_REF = "secret-ref:synthetic-only:rotation-7"
BLOB_REF = "blob-ref:synthetic-only:sha256-8a5edab282632443219e4"
BLOB_SIZE_BYTES = 25 * 1024 * 1024
REQUEST_DIGEST = hashlib.sha256(b"cloudhelm-p0-sdk05-sdk06-fixed-input-v1").hexdigest()


def _dsn() -> str:
    value = os.environ.setdefault(DSN_ENV, DEFAULT_DSN)
    libpq_dsn = value.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = conninfo_to_dict(libpq_dsn)
    expected = {
        "host": "127.0.0.1",
        "port": "55432",
        "dbname": "cloudhelm_p0",
        "user": "cloudhelm_probe",
    }
    if any(parts.get(key) != expected_value for key, expected_value in expected.items()):
        raise RuntimeError("probe requires the isolated local trust database at 127.0.0.1:55432/cloudhelm_p0")
    if parts.get("password"):
        raise RuntimeError("probe refuses a password-bearing database connection string")
    return value


def _libpq_dsn() -> str:
    return _dsn().replace("postgresql+psycopg://", "postgresql://", 1)


def _config(executor_id: str) -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "system_database_url": _dsn(),
        "dbos_system_schema": SYSTEM_SCHEMA,
        "application_version": os.environ[APP_VERSION_ENV],
        "executor_id": executor_id,
        "sys_db_pool_size": 4,
        "sys_db_polling_concurrency": 1,
        "max_executor_threads": 2,
        "run_migrations": False,
        "enable_otlp": False,
        "log_level": "CRITICAL",
        "console_log_level": "CRITICAL",
    }


def _ensure_business_tables() -> None:
    with psycopg.connect(_libpq_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {BUSINESS_SCHEMA}")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.workflow_results (
                operation_id text PRIMARY KEY,
                request_digest text NOT NULL,
                secret_ref text NOT NULL,
                blob_ref text NOT NULL,
                blob_size_bytes bigint NOT NULL,
                phase text NOT NULL,
                write_count integer NOT NULL CHECK (write_count = 1)
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.retry_attempts (
                operation_id text PRIMARY KEY,
                attempt_count integer NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.priority_events (
                event_no bigserial PRIMARY KEY,
                run_id text NOT NULL,
                workflow_id text NOT NULL,
                priority integer NOT NULL
            )
            """
        )


def _worker_main(executor_id: str, run_id: str) -> None:
    DBOS(config=_config(executor_id))
    DBOS.listen_queues(list(recovery_workflows.queue_names(run_id).values()))
    DBOS.launch()
    recovery_workflows.register_queues(run_id)
    while True:
        time.sleep(1)


def _start_worker(executor_id: str, run_id: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env[DSN_ENV] = _dsn()
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker", executor_id, run_id],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
    )
    _wait_for(lambda: process.poll() is None, 5, "worker process startup")
    return process


def _stop_worker(process: subprocess.Popen[bytes], *, kill: bool = False) -> int:
    if process.poll() is None:
        if kill:
            process.kill()
        else:
            process.send_signal(signal.SIGTERM)
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def _client() -> DBOSClient:
    return DBOSClient(
        system_database_url=_dsn(),
        dbos_system_schema=SYSTEM_SCHEMA,
        system_database_pool_size=4,
        system_database_polling_concurrency=1,
        use_listen_notify=False,
        application_name=APP_NAME,
    )


def _enqueue(
    client: DBOSClient,
    workflow_name: str,
    queue_name: str,
    workflow_id: str,
    *args: Any,
    priority: int = 1,
) -> str:
    handle = client.enqueue(
        EnqueueOptions(
            workflow_name=workflow_name,
            queue_name=queue_name,
            workflow_id=workflow_id,
            workflow_id_reuse_policy="reject",
            app_version=os.environ[APP_VERSION_ENV],
            application_name=APP_NAME,
            priority=priority,
        ),
        *args,
    )
    return handle.get_workflow_id()


def _workflow_status(client: DBOSClient, workflow_id: str) -> Any | None:
    found = client.list_workflows(
        workflow_ids=[workflow_id], load_input=True, load_output=True, limit=1
    )
    return found[0] if found else None


def _status_if(
    client: DBOSClient, workflow_id: str, predicate: Callable[[Any], bool]
) -> Any | None:
    state = _workflow_status(client, workflow_id)
    return state if state is not None and predicate(state) else None


def _wait_for(predicate: Callable[[], Any], timeout: float, label: str) -> Any:
    deadline = time.monotonic() + timeout
    last_value: Any = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {label}; last observed={last_value!r}")


def _result_after_success(client: DBOSClient, workflow_id: str) -> Any:
    status = _wait_for(
        lambda: _status_if(
            client,
            workflow_id,
            lambda state: state.status
            in {"SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"},
        ),
        40,
        f"workflow {workflow_id} terminal status",
    )
    if status.status != "SUCCESS":
        raise RuntimeError(f"workflow {workflow_id} ended with {status.status}")
    return client.retrieve_workflow(workflow_id).get_result(polling_interval_sec=0.1), status


def _contains(value: Any, needle: str) -> bool:
    return needle in repr(value)


def _business_result(operation_id: str) -> dict[str, Any] | None:
    with psycopg.connect(_libpq_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT request_digest, secret_ref, blob_ref, blob_size_bytes,
                   phase, write_count
            FROM {BUSINESS_SCHEMA}.workflow_results
            WHERE operation_id = %s
            """,
            (operation_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        "request_digest": row[0],
        "secret_ref": row[1],
        "blob_ref": row[2],
        "blob_size_bytes": row[3],
        "phase": row[4],
        "write_count": row[5],
    }


def _business_phase(operation_id: str, phase: str) -> dict[str, Any] | None:
    row = _business_result(operation_id)
    return row if row is not None and row["phase"] == phase else None


def _migration_version() -> int:
    with psycopg.connect(_libpq_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"SELECT version FROM {SYSTEM_SCHEMA}.dbos_migrations ORDER BY version DESC LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("DBOS public migration did not create a migration version marker")
    return int(row[0])


def _postgres_server_version() -> str:
    with psycopg.connect(_libpq_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('server_version')")
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL server version was unavailable")
    return str(row[0])


def _row_count(table: str, operation_id: str) -> int:
    with psycopg.connect(_libpq_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"SELECT attempt_count FROM {BUSINESS_SCHEMA}.{table} WHERE operation_id = %s",
            (operation_id,),
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _priority_order(run_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(_libpq_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT workflow_id, priority
            FROM {BUSINESS_SCHEMA}.priority_events
            WHERE run_id = %s
            ORDER BY event_no
            """,
            (run_id,),
        )
        return [{"workflow_id": row[0], "priority": row[1]} for row in cursor.fetchall()]


def _ensure_all_queues(
    client: DBOSClient, process: subprocess.Popen[bytes], run_id: str
) -> None:
    def queues_ready() -> bool:
        if process.poll() is not None:
            raise RuntimeError(f"worker exited during startup with code {process.returncode}")
        try:
            return all(
                client.retrieve_queue(queue_name) is not None
                for queue_name in recovery_workflows.queue_names(run_id).values()
            )
        except Exception:
            return False

    _wait_for(queues_ready, 15, "all registered queues")


def _main() -> dict[str, Any]:
    run_id = uuid4().hex[:12]
    app_version = f"p0.1-recovery-{run_id}"
    os.environ[APP_VERSION_ENV] = app_version
    _ensure_business_tables()
    DBOS.migrate(_dsn(), schema=SYSTEM_SCHEMA)
    migration_version = _migration_version()

    client = _client()
    worker: subprocess.Popen[bytes] | None = None
    report: dict[str, Any] = {
        "card_ids": ["SDK-05", "SDK-06"],
        "run_id": run_id,
        "observed_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "versions": {
            "python": sys.version.split()[0],
            "dbos": version("dbos"),
            "pydantic_ai": version("pydantic-ai-slim"),
            "psycopg": version("psycopg"),
            "sqlalchemy": version("sqlalchemy"),
            "postgresql_server": _postgres_server_version(),
            "postgresql_system_schema_migration": migration_version,
            "business_schema": BUSINESS_SCHEMA,
            "system_schema": SYSTEM_SCHEMA,
            "application_version": app_version,
        },
        "input": {
            "request_digest": REQUEST_DIGEST,
            "secret_ref": SECRET_REF,
            "blob_ref": BLOB_REF,
            "blob_size_bytes_metadata_only": BLOB_SIZE_BYTES,
            "actual_secret_or_blob_bytes_supplied": False,
            "canaries_are_noncredential_synthetic_values": True,
        },
    }
    queues = recovery_workflows.queue_names(run_id)

    try:
        worker = _start_worker(f"{run_id}-worker-a", run_id)
        _ensure_all_queues(client, worker, run_id)

        recovery_id = f"p0r-{run_id}-recover"
        operation_id = f"operation-{run_id}-checkpoint-gap"
        _enqueue(
            client,
            "p0.recovery.checkpoint_recovery",
            queues["orchestration"],
            recovery_id,
            operation_id,
            REQUEST_DIGEST,
            SECRET_REF,
            BLOB_REF,
            BLOB_SIZE_BYTES,
            PARAMETER_CANARY,
            True,
        )
        committed = _wait_for(
            lambda: _business_phase(operation_id, "committed_before_checkpoint"),
            25,
            "business commit before DBOS step checkpoint",
        )
        killed_worker_return_code = _stop_worker(worker, kill=True)
        worker = None
        retained_before_restart = _workflow_status(client, recovery_id)
        if retained_before_restart is None:
            raise RuntimeError("uncompleted recovery workflow disappeared before restart")

        worker = _start_worker(f"{run_id}-worker-a", run_id)
        _ensure_all_queues(client, worker, run_id)
        after_restart_status = _workflow_status(client, recovery_id)
        recovered_result, recovered_status = _result_after_success(client, recovery_id)
        recovered_business = _business_result(operation_id)

        failure_id = f"p0r-{run_id}-failure"
        failure_canary = f"{ERROR_CANARY}-{run_id}"
        _enqueue(
            client,
            "p0.recovery.failure_probe",
            queues["orchestration"],
            failure_id,
            failure_canary,
        )
        failed_status = _wait_for(
            lambda: _status_if(client, failure_id, lambda state: state.status == "ERROR"),
            20,
            "synthetic failure workflow",
        )
        failed_steps = client.list_workflow_steps(failure_id, load_output=True)
        error_canary_visible = _contains(failed_status.error, failure_canary) or any(
            _contains(step.get("error"), failure_canary) for step in failed_steps
        )
        parameter_canary_visible = _contains(recovered_status.input, PARAMETER_CANARY)
        allowed_output = {
            "operation_id",
            "request_digest",
            "secret_ref",
            "blob_ref",
            "blob_size_bytes",
            "write_count",
            "parameter_canary_present",
            "reused_business_result",
        }
        step_outputs = client.list_workflow_steps(recovery_id, load_output=True)
        step_output_fields = sorted(
            {
                key
                for step in step_outputs
                if isinstance(step.get("output"), dict)
                for key in step["output"]
            }
        )
        allowed_step_output_fields = allowed_output | {"inserted_this_attempt", "phase"}

        retry_id = f"p0r-{run_id}-retry"
        retry_operation = f"operation-{run_id}-retry"
        retry_canary = f"{ERROR_CANARY}-retry-{run_id}"
        _enqueue(
            client,
            "p0.recovery.retry_probe",
            queues["orchestration"],
            retry_id,
            retry_operation,
            retry_canary,
        )
        retry_result, retry_status = _result_after_success(client, retry_id)

        _stop_worker(worker)
        worker = None
        priority_1_id = f"p0r-{run_id}-priority-1"
        priority_9_id = f"p0r-{run_id}-priority-9"
        for workflow_id, priority in ((priority_9_id, 9), (priority_1_id, 1)):
            _enqueue(
                client,
                "p0.recovery.priority_probe",
            queues["priority"],
                workflow_id,
                run_id,
                workflow_id,
                priority,
                priority=priority,
            )
        pending_before_start = {
            workflow_id: _workflow_status(client, workflow_id).status
            for workflow_id in (priority_1_id, priority_9_id)
        }
        worker = _start_worker(f"{run_id}-worker-c", run_id)
        _ensure_all_queues(client, worker, run_id)
        for workflow_id in (priority_1_id, priority_9_id):
            _result_after_success(client, workflow_id)
        observed_priority_order = _priority_order(run_id)

        model_active_id = f"p0r-{run_id}-model-active"
        model_waiting_id = f"p0r-{run_id}-model-waiting"
        _enqueue(
            client,
            "p0.recovery.model_slot_hold",
            queues["model"],
            model_active_id,
            30.0,
        )
        _wait_for(
            lambda: _status_if(
                client, model_active_id, lambda state: state.dequeued_at is not None
            ),
            10,
            "model slot acquisition",
        )
        _enqueue(
            client,
            "p0.recovery.model_slot_hold",
            queues["model"],
            model_waiting_id,
            30.0,
        )
        waiting_status = _wait_for(
            lambda: _status_if(
                client, model_waiting_id, lambda state: state.status == "ENQUEUED"
            ),
            8,
            "second model workflow waiting at concurrency one",
        )

        control_id = f"p0r-{run_id}-control"
        _enqueue(
            client,
            "p0.recovery.control_probe",
            queues["control"],
            control_id,
            control_id,
        )
        control_started = time.monotonic()
        control_result, control_status = _result_after_success(client, control_id)
        control_elapsed_ms = round((time.monotonic() - control_started) * 1000, 1)

        query_started = time.monotonic()
        active_status = client.retrieve_workflow(model_active_id).get_status()
        query_elapsed_ms = round((time.monotonic() - query_started) * 1000, 1)
        cancel_started = time.monotonic()
        client.cancel_workflow(model_active_id)
        cancel_elapsed_ms = round((time.monotonic() - cancel_started) * 1000, 1)
        active_final = _wait_for(
            lambda: _status_if(
                client,
                model_active_id,
                lambda state: state.status in {"CANCELLED", "SUCCESS", "ERROR"},
            ),
            5,
            "model workflow cancellation status",
        )
        waiting_final = _workflow_status(client, model_waiting_id)
        if waiting_final and waiting_final.status not in {"SUCCESS", "ERROR", "CANCELLED"}:
            client.cancel_workflow(model_waiting_id)
            _wait_for(
                lambda: _status_if(
                    client, model_waiting_id, lambda state: state.status == "CANCELLED"
                ),
                5,
                "queued model workflow cancellation",
            )

        cleanup_id = control_id
        cleanup_before = _workflow_status(client, cleanup_id)
        if cleanup_before is None or cleanup_before.status != "SUCCESS":
            raise RuntimeError("cleanup candidate was not a completed workflow")
        client.delete_workflow(cleanup_id)
        cleanup_after = _workflow_status(client, cleanup_id)

        report["sdk05"] = {
            "result": "partial; default workflow inputs and terminal errors must be treated as persisted data",
            "worker_killed_after_business_commit_before_step_return": True,
            "worker_a_exit_code": killed_worker_return_code,
            "uncompleted_workflow_visible_before_restart": retained_before_restart.status,
            "same_executor_restart_status_before_recovery_wait": (
                after_restart_status.status if after_restart_status else None
            ),
            "executor_id_after_restart_launch": (
                after_restart_status.executor_id if after_restart_status else None
            ),
            "same_executor_id_reused": bool(
                after_restart_status
                and after_restart_status.executor_id == f"{run_id}-worker-a"
            ),
            "same_workflow_id_recovered_to": recovered_status.status,
            "recovery_attempts_after_restart": recovered_status.recovery_attempts,
            "recovery_output": recovered_result,
            "business_record_before_restart": committed,
            "business_record_after_restart": recovered_business,
            "business_write_count_after_restart": recovered_business["write_count"],
            "reused_existing_result": recovered_result["reused_business_result"],
            "synthetic_parameter_canary_visible_in_public_workflow_input": parameter_canary_visible,
            "synthetic_error_canary_visible_in_public_terminal_error": error_canary_visible,
            "step_output_fields": step_output_fields,
            "step_outputs_within_probe_allowlist": set(step_output_fields).issubset(
                allowed_step_output_fields
            ),
            "workflow_output_fields_within_probe_allowlist": set(recovered_result).issubset(allowed_output),
            "retry_attempt_count": _row_count("retry_attempts", retry_operation),
            "retry_result": retry_result,
            "retry_status": retry_status.status,
            "cleanup": {
                "pending_recovery_history_visible_until_recovered": (
                    retained_before_restart.status == "PENDING"
                ),
                "probe_did_not_call_delete_while_pending": True,
                "completed_unreferenced_control_history_deleted_via_public_api": True,
                "completed_control_history_visible_after_sdk_delete": cleanup_after is not None,
            },
            "pydantic_ai_dbos_adapter": {
                "version": "2.55.0",
                "source_review": "DBOSDurability routes model/MCP I/O through DBOS steps; the registered workflow accepts message_history and Conversation inputs; it does not redact the caller-supplied history.",
                "direct_reuse": "blocked for unbounded or sensitive histories until a supported bounded/redacted input boundary is validated",
                "real_model_call": False,
            },
        }
        report["sdk06"] = {
            "result": "partial; DBOS workflow recovery/control is observed; physical reservation is not implemented by this probe",
            "priority_queue": {
                "configured_worker_and_global_concurrency": 1,
                "queued_before_worker_start": pending_before_start,
                "observed_start_order": observed_priority_order,
                "lower_numeric_priority_first": bool(
                    observed_priority_order and observed_priority_order[0]["priority"] == 1
                ),
                "public_priority_field": True,
            },
            "model_queue": {
                "configured_worker_and_global_concurrency": 1,
                "second_workflow_status_while_first_dequeued": waiting_status.status,
                "second_workflow_dequeued_at_while_first_running": waiting_status.dequeued_at,
            },
            "control_while_model_slot_occupied": {
                "control_workflow_status": control_status.status,
                "control_workflow_elapsed_ms": control_elapsed_ms,
                "query_status": active_status.status,
                "query_elapsed_ms": query_elapsed_ms,
                "cancel_elapsed_ms": cancel_elapsed_ms,
                "model_workflow_final_status": active_final.status,
                "model_workflow_cancelled": active_final.status == "CANCELLED",
            },
            "system_database_client_pool_size": 4,
            "system_database_polling_concurrency": 1,
            "workflow_executor_threads": 2,
            "physical_resource_reservation": "not observed; a DBOS queue slot is not a Runner/host resource budget",
            "supplier_throughput_or_cost": "not tested; no model provider was called",
        }
        return report
    finally:
        if worker is not None:
            _stop_worker(worker)
        client.destroy()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        _worker_main(sys.argv[2], sys.argv[3])
        return 0
    if len(sys.argv) != 1:
        print("usage: probe_recovery.py [--worker EXECUTOR_ID]", file=sys.stderr)
        return 2
    try:
        print(json.dumps(_main(), ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(f"recovery probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
