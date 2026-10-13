"""DBOS public-API probe for ref-only checkpoint persistence boundaries."""

from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
import sys
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any
from uuid import uuid4

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.seam_checkpoint import (
    CheckpointConflict,
    CheckpointRetained,
    CheckpointStore,
    ContextReferences,
    InvalidContextReferences,
)


DEFAULT_DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
DSN_ENV = "CLOUDHELM_P0_DSN"
APP_NAME = "cloudhelm-p0-checkpoint-probe"
APP_VERSION_ENV = "CLOUDHELM_P0_APP_VERSION"
SYSTEM_SCHEMA = "dbos_p0_checkpoint"
QUEUE_NAME_PREFIX = "p0-checkpoint-"
WORKFLOW_NAME = "p0.checkpoint.ref_only"
STEP_NAME = "p0_checkpoint.consume_transient_inputs"
SAFE_FAILURE_CODE = "P0_CHECKPOINT_SAFE_FAILURE"
PAYLOAD_BYTES = 25 * 1024 * 1024
MAX_PERSISTED_STRING = 512


@dataclass(slots=True)
class _TransientFixture:
    secret_canary: str
    payload: bytes


_STORE: CheckpointStore | None = None
_TRANSIENT: dict[str, _TransientFixture] = {}
_SAFE_FAILURE_IDS: set[str] = set()
_ACTIVE_PHASE = "startup"


def install_store(store: CheckpointStore) -> None:
    global _STORE
    _STORE = store


def install_transient_fixture(
    checkpoint_id: str,
    secret_canary: str,
    payload: bytes,
    *,
    fail_safely: bool = False,
) -> None:
    _TRANSIENT[checkpoint_id] = _TransientFixture(secret_canary, payload)
    if fail_safely:
        _SAFE_FAILURE_IDS.add(checkpoint_id)


def clear_transient_fixture(checkpoint_id: str) -> None:
    _TRANSIENT.pop(checkpoint_id, None)
    _SAFE_FAILURE_IDS.discard(checkpoint_id)


@DBOS.step(name=STEP_NAME)
def _consume_transient_inputs(checkpoint_id: str) -> dict[str, Any]:
    if checkpoint_id in _SAFE_FAILURE_IDS:
        raise RuntimeError(SAFE_FAILURE_CODE)
    if _STORE is None or checkpoint_id not in _TRANSIENT:
        raise RuntimeError("P0_CHECKPOINT_TRANSIENT_INPUT_UNAVAILABLE")
    fixture = _TRANSIENT[checkpoint_id]
    refs = _STORE.get(checkpoint_id)
    if not fixture.secret_canary or len(fixture.payload) != PAYLOAD_BYTES:
        raise RuntimeError("P0_CHECKPOINT_TRANSIENT_INPUT_INVALID")
    # Consume both complete transient inputs without returning derived content.
    secret_consumed = len(sha256(fixture.secret_canary.encode("utf-8")).digest()) == 32
    artifact_consumed = len(sha256(fixture.payload).digest()) == 32
    return {
        "checkpoint_id": checkpoint_id,
        "secret_resource_ref": refs.secret_resource_ref,
        "artifact_ref": refs.artifact_ref,
        "blob_size_bytes": len(fixture.payload),
        "secret_consumed": secret_consumed and artifact_consumed,
    }


@DBOS.workflow(name=WORKFLOW_NAME)
def checkpoint_ref_only_workflow(checkpoint_id: str) -> dict[str, Any]:
    return _consume_transient_inputs(checkpoint_id)


def _dsn() -> str:
    value = os.environ.setdefault(DSN_ENV, DEFAULT_DSN)
    libpq_dsn = value.replace("postgresql+psycopg://", "postgresql://", 1)
    from psycopg.conninfo import conninfo_to_dict

    parts = conninfo_to_dict(libpq_dsn)
    expected = {
        "host": "127.0.0.1",
        "port": "55432",
        "dbname": "cloudhelm_p0",
        "user": "cloudhelm_probe",
    }
    if any(parts.get(key) != expected_value for key, expected_value in expected.items()):
        raise RuntimeError("P0_CHECKPOINT_UNSAFE_DATABASE_TARGET")
    if parts.get("password"):
        raise RuntimeError("P0_CHECKPOINT_PASSWORD_DSN_REFUSED")
    return value


def _dbos_config(run_id: str, dsn: str, app_version: str) -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "system_database_url": dsn,
        "dbos_system_schema": SYSTEM_SCHEMA,
        "application_version": app_version,
        "executor_id": f"p0-checkpoint-{run_id}-worker",
        "sys_db_pool_size": 3,
        "sys_db_polling_concurrency": 1,
        "max_executor_threads": 2,
        "run_migrations": True,
        "enable_otlp": False,
        "use_listen_notify": False,
        "log_level": "CRITICAL",
        "console_log_level": "CRITICAL",
    }


def _terminal_status(client: DBOSClient, workflow_id: str) -> Any:
    deadline = time.monotonic() + 20
    terminal = {"SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"}
    while time.monotonic() < deadline:
        rows = client.list_workflows(
            workflow_ids=[workflow_id],
            load_input=True,
            load_output=True,
            limit=1,
        )
        if rows and rows[0].status in terminal:
            return rows[0]
        time.sleep(0.05)
    raise TimeoutError("P0_CHECKPOINT_WORKFLOW_TIMEOUT")


def _bounded_tree(value: Any, secret_canary: str) -> tuple[bool, int]:
    """Return (unsafe, node_count) without formatting large values."""
    stack = [value]
    nodes = 0
    unsafe = False
    while stack:
        current = stack.pop()
        nodes += 1
        if nodes > 2048:
            return True, nodes
        if isinstance(current, str):
            unsafe |= len(current) > MAX_PERSISTED_STRING or secret_canary in current
        elif isinstance(current, (bytes, bytearray, memoryview)):
            raw = bytes(current) if len(current) <= MAX_PERSISTED_STRING else b""
            unsafe |= len(current) > MAX_PERSISTED_STRING or secret_canary.encode() in raw
        elif isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, (list, tuple, set, frozenset)):
            stack.extend(current)
        elif current is None or isinstance(current, (bool, int, float)):
            continue
        else:
            unsafe |= len(str(current)) > MAX_PERSISTED_STRING
    return unsafe, nodes


def _assert_safe_history(
    client: DBOSClient,
    workflow_id: str,
    checkpoint_id: str,
    secret_canary: str,
    *,
    expect_failure: bool,
) -> dict[str, int]:
    global _ACTIVE_PHASE
    _ACTIVE_PHASE = "public workflow status lookup"
    status = _terminal_status(client, workflow_id)
    if status.input != {"args": (checkpoint_id,), "kwargs": {}}:
        raise AssertionError("P0_CHECKPOINT_WORKFLOW_INPUT_NOT_REF_ONLY")
    if expect_failure:
        _ACTIVE_PHASE = "safe failure status inspection"
        if status.status != "ERROR" or status.error is None:
            raise AssertionError("P0_CHECKPOINT_FAILURE_NOT_OBSERVED")
        if str(status.error) != SAFE_FAILURE_CODE:
            raise AssertionError("P0_CHECKPOINT_UNSAFE_WORKFLOW_ERROR")
        workflow_roots: list[Any] = [status.input, status.output, str(status.error)]
    else:
        _ACTIVE_PHASE = "successful workflow input inspection"
        if status.status != "SUCCESS":
            raise AssertionError("P0_CHECKPOINT_SUCCESS_NOT_OBSERVED")
        workflow_roots = [status.input, status.output]

    _ACTIVE_PHASE = "public step history lookup"
    steps = client.list_workflow_steps(workflow_id, load_output=True)
    _ACTIVE_PHASE = "public step history inspection"
    if len(steps) != 1 or steps[0].get("function_name") != STEP_NAME:
        raise AssertionError("P0_CHECKPOINT_STEP_HISTORY_SHAPE_INVALID")
    step = steps[0]
    if expect_failure:
        if step.get("error") is None or str(step["error"]) != SAFE_FAILURE_CODE:
            raise AssertionError("P0_CHECKPOINT_UNSAFE_STEP_ERROR")
        workflow_roots.append(str(step["error"]))
        workflow_roots.append(step.get("output"))
    else:
        allowed_keys = {
            "checkpoint_id",
            "secret_resource_ref",
            "artifact_ref",
            "blob_size_bytes",
            "secret_consumed",
        }
        step_output = step.get("output")
        if not isinstance(step_output, dict) or set(step_output) != allowed_keys:
            raise AssertionError("P0_CHECKPOINT_STEP_RESULT_SHAPE_INVALID")
        if step_output["checkpoint_id"] != checkpoint_id:
            raise AssertionError("P0_CHECKPOINT_STEP_CHECKPOINT_ID_MISMATCH")
        if step_output["blob_size_bytes"] != PAYLOAD_BYTES or not step_output["secret_consumed"]:
            raise AssertionError("P0_CHECKPOINT_TRANSIENT_CONSUMPTION_MISSING")
        workflow_roots.append(step_output)

    nodes = 0
    for root in workflow_roots:
        unsafe, count = _bounded_tree(root, secret_canary)
        nodes += count
        if unsafe:
            raise AssertionError("P0_CHECKPOINT_UNSAFE_PERSISTED_HISTORY")
    return {"step_count": len(steps), "inspected_nodes": nodes}


def _enqueue(
    client: DBOSClient,
    queue_name: str,
    app_version: str,
    workflow_id: str,
    checkpoint_id: str,
) -> str:
    handle = client.enqueue(
        EnqueueOptions(
            workflow_name=WORKFLOW_NAME,
            queue_name=queue_name,
            workflow_id=workflow_id,
            workflow_id_reuse_policy="return-existing",
            app_version=app_version,
            application_name=APP_NAME,
        ),
        checkpoint_id,
    )
    return handle.get_workflow_id()


def _references(run_id: str, suffix: str = "") -> ContextReferences:
    stem = f"p0-checkpoint:{run_id}{suffix}"
    return ContextReferences(
        requirement_ref=f"requirement-ref:{stem}",
        input_set_ref=f"input-set-ref:{stem}:v1",
        history_ref=f"history-ref:{stem}:v1",
        artifact_ref=f"artifact-ref:{stem}:sha256-9c56cc51b374c3ba",
        secret_resource_ref=f"secret-resource-ref:{stem}:rotation-1",
    )


def _verify_validation_and_idempotency(store: CheckpointStore, run_id: str) -> dict[str, int]:
    base = _references(run_id)
    checkpoint_id = store.put(base)
    if store.put(base) != checkpoint_id or store.get(checkpoint_id) != base:
        raise AssertionError("P0_CHECKPOINT_IDEMPOTENCY_FAILED")
    changed = base.model_copy(update={"artifact_ref": base.artifact_ref + ":changed"})
    try:
        store.put(changed)
    except CheckpointConflict:
        pass
    else:
        raise AssertionError("P0_CHECKPOINT_DIGEST_CONFLICT_NOT_REJECTED")

    rejected = 0
    for field in ("raw_history", "history", "messages", "content", "raw_error", "secret_value"):
        payload = base.model_dump()
        payload[field] = "synthetic-rejected-value"
        try:
            store.put(payload)
        except InvalidContextReferences as error:
            if str(error) != "P0_CHECKPOINT_INVALID_REFERENCES":
                raise AssertionError("P0_CHECKPOINT_VALIDATION_ERROR_UNSAFE") from None
            rejected += 1
        else:
            raise AssertionError("P0_CHECKPOINT_EXTRA_FIELD_ACCEPTED")
    too_long = base.model_dump()
    too_long["history_ref"] = "r" * (MAX_PERSISTED_STRING + 1)
    try:
        store.put(too_long)
    except InvalidContextReferences:
        rejected += 1
    else:
        raise AssertionError("P0_CHECKPOINT_UNBOUNDED_REFERENCE_ACCEPTED")
    try:
        store.cleanup(checkpoint_id)
    except CheckpointRetained:
        pass
    else:
        raise AssertionError("P0_CHECKPOINT_ACTIVE_REFERENCE_CLEANED")
    store.mark_terminal(checkpoint_id)
    store.cleanup(checkpoint_id)
    return {
        "checkpoint_id_length": len(checkpoint_id),
        "invalid_shapes_rejected": rejected,
        "terminal_validation_row_cleaned": True,
    }


def run_probe() -> dict[str, Any]:
    global _ACTIVE_PHASE
    run_id = uuid4().hex[:12]
    _ACTIVE_PHASE = "database target validation"
    dsn = _dsn()
    app_version = os.environ.setdefault(APP_VERSION_ENV, f"p0.1-checkpoint-{run_id}")
    queue_name = f"{QUEUE_NAME_PREFIX}{run_id}"
    engine: Engine = create_engine(dsn, pool_size=2, max_overflow=0, pool_pre_ping=True)
    store = CheckpointStore(engine)
    _ACTIVE_PHASE = "checkpoint schema bootstrap"
    store.bootstrap()
    _ACTIVE_PHASE = "reference validation and idempotency"
    validation = _verify_validation_and_idempotency(store, run_id)
    success_refs = _references(run_id, "-success")
    failure_refs = _references(run_id, "-failure")
    success_id = store.put(success_refs)
    failure_id = store.put(failure_refs)
    secret_canary = f"SYNTHETIC-SECRET-CANARY-{run_id}"
    payload = b"x" * PAYLOAD_BYTES
    install_store(store)
    install_transient_fixture(success_id, secret_canary, payload)
    install_transient_fixture(failure_id, secret_canary, payload, fail_safely=True)

    runtime_started = False
    client: DBOSClient | None = None
    try:
        _ACTIVE_PHASE = "DBOS runtime startup"
        DBOS(config=_dbos_config(run_id, dsn, app_version))
        DBOS.launch()
        runtime_started = True
        DBOS.register_queue(queue_name, worker_concurrency=1, global_concurrency=1)
        client = DBOSClient(
            system_database_url=dsn,
            dbos_system_schema=SYSTEM_SCHEMA,
            system_database_pool_size=3,
            system_database_polling_concurrency=1,
            use_listen_notify=False,
            application_name=APP_NAME,
        )

        _ACTIVE_PHASE = "successful workflow and public history inspection"
        success_workflow_id = f"p0c-{run_id}-success"
        if _enqueue(client, queue_name, app_version, success_workflow_id, success_id) != success_workflow_id:
            raise AssertionError("P0_CHECKPOINT_WORKFLOW_ID_CHANGED")
        success_history = _assert_safe_history(
            client, success_workflow_id, success_id, secret_canary, expect_failure=False
        )
        success_result = client.retrieve_workflow(success_workflow_id).get_result(
            polling_interval_sec=0.05
        )
        replayed_id = _enqueue(client, queue_name, app_version, success_workflow_id, success_id)
        replayed_result = client.retrieve_workflow(replayed_id).get_result(polling_interval_sec=0.05)
        if replayed_id != success_workflow_id or replayed_result != success_result:
            raise AssertionError("P0_CHECKPOINT_REPLAY_CHANGED_RESULT")

        _ACTIVE_PHASE = "safe failure and public history inspection"
        failure_workflow_id = f"p0c-{run_id}-failure"
        if _enqueue(client, queue_name, app_version, failure_workflow_id, failure_id) != failure_workflow_id:
            raise AssertionError("P0_CHECKPOINT_FAILURE_WORKFLOW_ID_CHANGED")
        failure_history = _assert_safe_history(
            client, failure_workflow_id, failure_id, secret_canary, expect_failure=True
        )

        _ACTIVE_PHASE = "terminal release and checkpoint cleanup"
        store.mark_terminal(success_id)
        store.mark_terminal(failure_id)
        store.cleanup(success_id)
        store.cleanup(failure_id)
        report = {
            "card": "P0.1-A01b-checkpoint",
            "status": "probe_passed",
            "run_id": run_id,
            "dbos_version": version("dbos"),
            "schema": "p0_checkpoint",
            "payload_bytes_consumed_in_memory": PAYLOAD_BYTES,
            "workflow_parameters": "checkpoint_id only",
            "public_step_inspection": "DBOSClient.list_workflow_steps",
            "success_workflow_id": success_workflow_id,
            "failure_workflow_id": failure_workflow_id,
            "same_workflow_replay_same_result": True,
            "safe_failure_code": SAFE_FAILURE_CODE,
            "success_history": success_history,
            "failure_history": failure_history,
            "retention": "held through terminal DBOS status; cleanup then allowed",
            "validation": validation,
            "pydantic_ai_default_dbos_wrapper": "not approved for untrimmed history; thin @workflow/@step seam only",
        }
        return report
    finally:
        clear_transient_fixture(success_id)
        clear_transient_fixture(failure_id)
        if client is not None:
            client.destroy()
        if runtime_started:
            DBOS.destroy()
        engine.dispose()


def main() -> int:
    try:
        report = run_probe()
    except Exception as error:
        print(
            json.dumps(
                {
                    "card": "P0.1-A01b-checkpoint",
                    "status": "probe_failed",
                    "phase": _ACTIVE_PHASE,
                    "exception_type": type(error).__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
