"""Small DBOS workflows used only by the P0.1 recovery probes."""

from __future__ import annotations

import os
import time
from typing import Any

import psycopg
from dbos import DBOS


BUSINESS_SCHEMA = "p0_recovery"
_QUEUE_NAMES = {
    "orchestration": "p0-recovery-orchestration",
    "model": "p0-recovery-model-calls",
    "control": "p0-recovery-control",
    "priority": "p0-recovery-priority",
}


def _business_dsn() -> str:
    sqlalchemy_dsn = os.environ["CLOUDHELM_P0_DSN"]
    return sqlalchemy_dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def queue_names(run_id: str) -> dict[str, str]:
    return {key: f"{base}-{run_id}" for key, base in _QUEUE_NAMES.items()}


def register_queues(run_id: str) -> None:
    for name in queue_names(run_id).values():
        DBOS.register_queue(
            name,
            worker_concurrency=1,
            global_concurrency=1,
            on_conflict="always_update",
        )


@DBOS.step(name="p0_recovery.persist_business_result")
def persist_business_result(
    operation_id: str,
    request_digest: str,
    secret_ref: str,
    blob_ref: str,
    blob_size_bytes: int,
    hold_after_commit: bool,
) -> dict[str, Any]:
    inserted = False
    with psycopg.connect(_business_dsn()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {BUSINESS_SCHEMA}.workflow_results
                    (operation_id, request_digest, secret_ref, blob_ref,
                     blob_size_bytes, phase, write_count)
                VALUES (%s, %s, %s, %s, %s, %s, 1)
                ON CONFLICT (operation_id) DO NOTHING
                RETURNING operation_id
                """,
                (
                    operation_id,
                    request_digest,
                    secret_ref,
                    blob_ref,
                    blob_size_bytes,
                    "committed_before_checkpoint" if hold_after_commit else "committed",
                ),
            )
            inserted = cursor.fetchone() is not None
            cursor.execute(
                f"""
                SELECT request_digest, secret_ref, blob_ref, blob_size_bytes, write_count
                FROM {BUSINESS_SCHEMA}.workflow_results
                WHERE operation_id = %s
                """,
                (operation_id,),
            )
            stored = cursor.fetchone()

    expected = (request_digest, secret_ref, blob_ref, blob_size_bytes, 1)
    if stored != expected:
        raise ValueError("stable operation identity was reused with different input")

    if inserted and hold_after_commit:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            time.sleep(0.025)
        raise TimeoutError("recovery probe did not restart the worker in time")

    return {
        "operation_id": operation_id,
        "request_digest": request_digest,
        "secret_ref": secret_ref,
        "blob_ref": blob_ref,
        "blob_size_bytes": blob_size_bytes,
        "write_count": stored[4],
        "inserted_this_attempt": inserted,
    }


@DBOS.step(name="p0_recovery.mark_replayed")
def mark_replayed(operation_id: str) -> dict[str, str]:
    with psycopg.connect(_business_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {BUSINESS_SCHEMA}.workflow_results
            SET phase = 'replayed_after_worker_restart'
            WHERE operation_id = %s AND phase = 'committed_before_checkpoint'
            RETURNING phase
            """,
            (operation_id,),
        )
        row = cursor.fetchone()
    return {"phase": row[0] if row else "already_recorded"}


@DBOS.workflow(name="p0.recovery.checkpoint_recovery")
def checkpoint_recovery_workflow(
    operation_id: str,
    request_digest: str,
    secret_ref: str,
    blob_ref: str,
    blob_size_bytes: int,
    parameter_canary: str,
    hold_after_commit: bool,
) -> dict[str, Any]:
    result = persist_business_result(
        operation_id,
        request_digest,
        secret_ref,
        blob_ref,
        blob_size_bytes,
        hold_after_commit,
    )
    if not result["inserted_this_attempt"]:
        mark_replayed(operation_id)
    return {
        "operation_id": operation_id,
        "request_digest": request_digest,
        "secret_ref": secret_ref,
        "blob_ref": blob_ref,
        "blob_size_bytes": blob_size_bytes,
        "write_count": result["write_count"],
        "parameter_canary_present": bool(parameter_canary),
        "reused_business_result": not result["inserted_this_attempt"],
    }


@DBOS.step(
    name="p0_recovery.retryable_synthetic_step",
    retries_allowed=True,
    interval_seconds=0.05,
    max_attempts=2,
)
def retryable_synthetic_step(operation_id: str, error_canary: str) -> dict[str, Any]:
    with psycopg.connect(_business_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {BUSINESS_SCHEMA}.retry_attempts AS existing (operation_id, attempt_count)
            VALUES (%s, 1)
            ON CONFLICT (operation_id) DO UPDATE
                SET attempt_count = existing.attempt_count + 1
            RETURNING attempt_count
            """,
            (operation_id,),
        )
        attempt_count = cursor.fetchone()[0]
    if attempt_count == 1:
        raise RuntimeError(f"synthetic noncredential failure canary: {error_canary}")
    return {"attempt_count": attempt_count, "outcome": "recovered"}


@DBOS.workflow(name="p0.recovery.retry_probe")
def retry_probe_workflow(operation_id: str, error_canary: str) -> dict[str, Any]:
    return retryable_synthetic_step(operation_id, error_canary)


@DBOS.step(name="p0_recovery.permanent_synthetic_failure")
def permanent_synthetic_failure(error_canary: str) -> None:
    raise RuntimeError(f"synthetic noncredential terminal error canary: {error_canary}")


@DBOS.workflow(name="p0.recovery.failure_probe", max_recovery_attempts=1)
def failure_probe_workflow(error_canary: str) -> None:
    permanent_synthetic_failure(error_canary)


@DBOS.workflow(name="p0.recovery.priority_probe")
def priority_probe_workflow(run_id: str, workflow_id: str, priority: int) -> dict[str, Any]:
    with psycopg.connect(_business_dsn()) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {BUSINESS_SCHEMA}.priority_events (run_id, workflow_id, priority)
            VALUES (%s, %s, %s)
            RETURNING event_no
            """,
            (run_id, workflow_id, priority),
        )
        event_no = cursor.fetchone()[0]
    return {"workflow_id": workflow_id, "priority": priority, "event_no": event_no}


@DBOS.workflow(name="p0.recovery.model_slot_hold")
async def model_slot_hold_workflow(seconds: float) -> dict[str, str]:
    await DBOS.sleep_async(seconds)
    return {"state": "released"}


@DBOS.workflow(name="p0.recovery.control_probe")
def control_probe_workflow(probe_id: str) -> dict[str, str]:
    return {"probe_id": probe_id, "state": "responsive"}
