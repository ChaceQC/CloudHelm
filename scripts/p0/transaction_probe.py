from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import platform
import time
import uuid
from typing import Any

from dbos import DBOS, DBOSClient, DBOSConfig, EnqueueOptions
from rfc8785 import dumps as jcs_dumps
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema


SYNC_DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
ASYNC_DSN = SYNC_DSN
BUSINESS_SCHEMA = "p0_transaction"
DBOS_SCHEMA = "dbos_p0_transaction"
APP_NAME = "cloudhelm-p0-sdk01"
APP_VERSION = "sdk01-p0.1"
QUEUE_NAME = "p0-sdk01-transaction-probe"
WORKFLOW_NAME = "sdk01_transaction_probe"
BASE_TASK_VERSION = 7
BASE_RUN_VERSION = 3

metadata = MetaData()
task_state = Table(
    "task_state",
    metadata,
    Column("task_id", String(160), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("version", Integer, nullable=False),
    Column("last_command_id", String(200), nullable=False),
    schema=BUSINESS_SCHEMA,
)
agent_run_state = Table(
    "agent_run_state",
    metadata,
    Column("agent_run_id", String(160), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("outcome", String(80), nullable=True),
    Column("version", Integer, nullable=False),
    Column("last_command_id", String(200), nullable=False),
    schema=BUSINESS_SCHEMA,
)
operation_records = Table(
    "operation_records",
    metadata,
    Column("operation_id", String(200), primary_key=True),
    Column("command_id", String(200), nullable=False, unique=True),
    Column("kind", String(80), nullable=False),
    Column("request_digest", String(80), nullable=False),
    schema=BUSINESS_SCHEMA,
)
command_results = Table(
    "command_results",
    metadata,
    Column("command_id", String(200), primary_key=True),
    Column("caller", String(160), nullable=False),
    Column("scope_id", String(160), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("request_digest", String(80), nullable=False),
    Column("result_json", JSONB, nullable=True),
    UniqueConstraint(
        "caller", "scope_id", "idempotency_key", name="uq_command_identity"
    ),
    schema=BUSINESS_SCHEMA,
)
event_log = Table(
    "event_log",
    metadata,
    Column("event_id", String(200), primary_key=True),
    Column("command_id", String(200), nullable=False, unique=True),
    Column("operation_id", String(200), nullable=False),
    Column("event_type", String(80), nullable=False),
    Column("outcome", String(80), nullable=False),
    Column("request_digest", String(80), nullable=False),
    schema=BUSINESS_SCHEMA,
)
workflow_bindings = Table(
    "workflow_bindings",
    metadata,
    Column("workflow_id", String(200), primary_key=True),
    Column("command_id", String(200), nullable=False, unique=True),
    Column("operation_id", String(200), nullable=False),
    Column("workflow_name", String(160), nullable=False),
    Column("application_name", String(160), nullable=False),
    Column("request_digest", String(80), nullable=False),
    Column("code_version", String(80), nullable=False),
    schema=BUSINESS_SCHEMA,
)


class InjectedFailure(RuntimeError):
    pass


class IdentityDigestConflict(RuntimeError):
    pass


@DBOS.workflow(name=WORKFLOW_NAME)
def sdk01_transaction_workflow(request_digest: str) -> str:
    return request_digest


def digest_request(envelope: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(jcs_dumps(envelope)).hexdigest()


def make_case(run_token: str, suffix: str = "") -> dict[str, Any]:
    prefix = f"sdk01-{run_token}{suffix}"
    caller = "agent-session:sdk01-probe"
    task_id = f"{prefix}-task"
    run_id = f"{prefix}-agent-run"
    identity = {
        "caller": caller,
        "scope_id": task_id,
        "idempotency_key": f"{prefix}-end-run",
        "command_id": f"{prefix}-command",
        "workflow_id": f"{prefix}-workflow",
        "operation_id": f"{prefix}-operation",
        "event_id": f"{prefix}-event",
        "task_id": task_id,
        "agent_run_id": run_id,
    }
    request = {
        "digest_config_version": "cloudhelm-jcs-v1",
        "request_schema_version": "end-run.v1",
        "caller": caller,
        "scope": {"task_id": task_id},
        "target": {
            "task_id": task_id,
            "agent_run_id": run_id,
            "operation_id": identity["operation_id"],
        },
        "command_type": "end_run",
        "request": {
            "expected_task_version": BASE_TASK_VERSION,
            "expected_run_version": BASE_RUN_VERSION,
            "outcome": "submitted",
        },
    }
    identity["request"] = request
    identity["request_digest"] = digest_request(request)
    return identity


def create_business_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(DropSchema(BUSINESS_SCHEMA, cascade=True, if_exists=True))
        connection.execute(CreateSchema(BUSINESS_SCHEMA, if_not_exists=True))
        metadata.create_all(connection)


def seed_case(engine: Engine, case: dict[str, Any]) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(task_state).values(
                task_id=case["task_id"],
                status="active",
                version=BASE_TASK_VERSION,
                last_command_id="seed",
            )
        )
        connection.execute(
            insert(agent_run_state).values(
                agent_run_id=case["agent_run_id"],
                status="running",
                outcome=None,
                version=BASE_RUN_VERSION,
                last_command_id="seed",
            )
        )


def enqueue_options(case: dict[str, Any]) -> EnqueueOptions:
    return {
        "workflow_name": WORKFLOW_NAME,
        "queue_name": QUEUE_NAME,
        "workflow_id": case["workflow_id"],
        "workflow_id_reuse_policy": "return-existing",
        "app_version": APP_VERSION,
        "application_name": APP_NAME,
    }


def inject_if_requested(fail_at: str | None, point: str) -> None:
    if fail_at == point:
        raise InjectedFailure(point)


def apply_command(
    connection: Connection,
    client: DBOSClient,
    case: dict[str, Any],
    fail_at: str | None = None,
) -> dict[str, Any]:
    identity = (
        command_results.c.caller == case["caller"],
        command_results.c.scope_id == case["scope_id"],
        command_results.c.idempotency_key == case["idempotency_key"],
    )
    existing = connection.execute(
        select(command_results).where(*identity)
    ).mappings().first()
    if existing is not None:
        if (
            existing["command_id"] != case["command_id"]
            or existing["request_digest"] != case["request_digest"]
        ):
            raise IdentityDigestConflict("same caller/scope/key has a different identity or digest")
        return existing["result_json"]

    task_version = case["request"]["request"]["expected_task_version"] + 1
    run_version = case["request"]["request"]["expected_run_version"] + 1
    result = {
        "command_id": case["command_id"],
        "request_digest": case["request_digest"],
        "task_version": task_version,
        "agent_run_version": run_version,
        "agent_run_status": "succeeded",
        "agent_run_outcome": case["request"]["request"]["outcome"],
        "operation_id": case["operation_id"],
        "event_id": case["event_id"],
        "workflow_id": case["workflow_id"],
    }
    connection.execute(
        insert(command_results).values(
            command_id=case["command_id"],
            caller=case["caller"],
            scope_id=case["scope_id"],
            idempotency_key=case["idempotency_key"],
            request_digest=case["request_digest"],
            result_json=result,
        )
    )
    task_update = connection.execute(
        update(task_state)
        .where(
            task_state.c.task_id == case["task_id"],
            task_state.c.status == "active",
            task_state.c.version == BASE_TASK_VERSION,
        )
        .values(version=task_version, last_command_id=case["command_id"])
    )
    run_update = connection.execute(
        update(agent_run_state)
        .where(
            agent_run_state.c.agent_run_id == case["agent_run_id"],
            agent_run_state.c.status == "running",
            agent_run_state.c.version == BASE_RUN_VERSION,
        )
        .values(
            status="succeeded",
            outcome=case["request"]["request"]["outcome"],
            version=run_version,
            last_command_id=case["command_id"],
        )
    )
    if task_update.rowcount != 1 or run_update.rowcount != 1:
        raise AssertionError("fixed source states or expected versions did not match")
    connection.execute(
        insert(operation_records).values(
            operation_id=case["operation_id"],
            command_id=case["command_id"],
            kind="end_run_follow_up",
            request_digest=case["request_digest"],
        )
    )
    inject_if_requested(fail_at, "domain_writes")

    connection.execute(
        insert(event_log).values(
            event_id=case["event_id"],
            command_id=case["command_id"],
            operation_id=case["operation_id"],
            event_type="agent_run.succeeded",
            outcome=case["request"]["request"]["outcome"],
            request_digest=case["request_digest"],
        )
    )
    inject_if_requested(fail_at, "event")

    connection.execute(
        insert(workflow_bindings).values(
            workflow_id=case["workflow_id"],
            command_id=case["command_id"],
            operation_id=case["operation_id"],
            workflow_name=WORKFLOW_NAME,
            application_name=APP_NAME,
            request_digest=case["request_digest"],
            code_version=APP_VERSION,
        )
    )
    inject_if_requested(fail_at, "workflow_binding")

    client.enqueue_in_transaction(
        connection, enqueue_options(case), case["request_digest"]
    )
    inject_if_requested(fail_at, "enqueue")
    return result


def count_for(connection: Connection, table: Table, *conditions: Any) -> int:
    return int(connection.execute(select(func.count()).select_from(table).where(*conditions)).scalar_one())


def assert_rollback(engine: Engine, case: dict[str, Any]) -> dict[str, Any]:
    with engine.connect() as connection:
        task = connection.execute(
            select(task_state).where(task_state.c.task_id == case["task_id"])
        ).mappings().one()
        run = connection.execute(
            select(agent_run_state).where(
                agent_run_state.c.agent_run_id == case["agent_run_id"]
            )
        ).mappings().one()
        assert (task["status"], task["version"], task["last_command_id"]) == (
            "active",
            BASE_TASK_VERSION,
            "seed",
        )
        assert (run["status"], run["outcome"], run["version"], run["last_command_id"]) == (
            "running",
            None,
            BASE_RUN_VERSION,
            "seed",
        )
        assert count_for(
            connection,
            operation_records,
            operation_records.c.operation_id == case["operation_id"],
        ) == 0
        assert count_for(
            connection,
            command_results,
            command_results.c.command_id == case["command_id"],
        ) == 0
        assert count_for(
            connection, event_log, event_log.c.command_id == case["command_id"]
        ) == 0
        assert count_for(
            connection,
            workflow_bindings,
            workflow_bindings.c.workflow_id == case["workflow_id"],
        ) == 0
    dbos_status = DBOS.get_workflow_status(case["workflow_id"])
    assert dbos_status is None
    return {
        "task": {"status": task["status"], "version": task["version"]},
        "agent_run": {
            "status": run["status"],
            "outcome": run["outcome"],
            "version": run["version"],
        },
        "command_rows": 0,
        "operation_rows": 0,
        "event_rows": 0,
        "workflow_binding_rows": 0,
        "dbos_public_status": "absent",
    }


def verify_committed(engine: Engine, case: dict[str, Any]) -> dict[str, Any]:
    with engine.connect() as connection:
        task = connection.execute(
            select(task_state).where(task_state.c.task_id == case["task_id"])
        ).mappings().one()
        run = connection.execute(
            select(agent_run_state).where(
                agent_run_state.c.agent_run_id == case["agent_run_id"]
            )
        ).mappings().one()
        command = connection.execute(
            select(command_results).where(
                command_results.c.command_id == case["command_id"]
            )
        ).mappings().one()
        event_count = count_for(
            connection, event_log, event_log.c.command_id == case["command_id"]
        )
        event = connection.execute(
            select(event_log).where(event_log.c.command_id == case["command_id"])
        ).mappings().one()
        operation_count = count_for(
            connection,
            operation_records,
            operation_records.c.operation_id == case["operation_id"],
        )
        binding_count = count_for(
            connection,
            workflow_bindings,
            workflow_bindings.c.workflow_id == case["workflow_id"],
        )
    assert (task["status"], task["version"]) == ("active", BASE_TASK_VERSION + 1)
    assert (run["status"], run["outcome"], run["version"]) == (
        "succeeded",
        "submitted",
        BASE_RUN_VERSION + 1,
    )
    assert operation_count == event_count == binding_count == 1
    assert command["request_digest"] == case["request_digest"]
    assert event["event_type"] == "agent_run.succeeded"
    assert event["outcome"] == "submitted"
    assert command["result_json"]["operation_id"] == case["operation_id"]
    assert command["result_json"]["workflow_id"] == case["workflow_id"]
    return command["result_json"]


def wait_for_workflow(client: DBOSClient, workflow_id: str) -> str:
    handle = client.retrieve_workflow(workflow_id)
    deadline = time.monotonic() + 10
    while True:
        status = handle.get_status()
        if status.status == "SUCCESS":
            return handle.get_result(polling_interval_sec=0.05)
        if status.status in {"ERROR", "MAX_RECOVERY_ATTEMPTS_EXCEEDED", "CANCELLED"}:
            raise AssertionError(f"public DBOS query returned terminal status {status.status}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"workflow did not finish; public status={status.status}")
        time.sleep(0.05)


async def async_rollback_probe(
    async_engine: Any,
    engine: Engine,
    client: DBOSClient,
    case: dict[str, Any],
) -> None:
    seed_case(engine, case)
    try:
        async with async_engine.begin() as async_connection:
            await async_connection.run_sync(
                lambda connection: apply_command(
                    connection, client, case, fail_at="enqueue"
                )
            )
    except InjectedFailure as failure:
        if str(failure) != "enqueue":
            raise
    else:
        raise AssertionError("async run_sync enqueue failure was not injected")


def main() -> None:
    run_token = uuid.uuid4().hex[:12]
    engine = create_engine(
        SYNC_DSN,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"application_name": "cloudhelm_sdk01_probe"},
    )
    async_engine = create_async_engine(ASYNC_DSN, pool_size=1, max_overflow=0)
    client: DBOSClient | None = None
    runtime_constructed = False
    report: dict[str, Any] = {
        "card": "SDK-01",
        "status": "running",
        "run_id": run_token,
        "business_schema": BUSINESS_SCHEMA,
        "dbos_system_schema": DBOS_SCHEMA,
        "conductor": "disabled; no key or URL configured",
    }
    try:
        create_business_schema(engine)
        DBOS(
            config=DBOSConfig(
                name=APP_NAME,
                system_database_url=SYNC_DSN,
                dbos_system_schema=DBOS_SCHEMA,
                application_version=APP_VERSION,
                executor_id=f"sdk01-{run_token}",
                enable_otlp=False,
                use_listen_notify=False,
                run_migrations=True,
                log_level="WARNING",
                console_log_level="WARNING",
            )
        )
        runtime_constructed = True
        DBOS.launch()
        DBOS.register_queue(QUEUE_NAME, worker_concurrency=1)
        client = DBOSClient(
            system_database_engine=engine,
            dbos_system_schema=DBOS_SCHEMA,
            application_name=APP_NAME,
            retry_connection_errors=False,
        )
        with engine.connect() as connection:
            server_version = connection.execute(
                select(func.current_setting("server_version"))
            ).scalar_one()
        report["versions"] = {
            "python": platform.python_version(),
            "dbos": importlib.metadata.version("dbos"),
            "sqlalchemy": importlib.metadata.version("sqlalchemy"),
            "psycopg": importlib.metadata.version("psycopg"),
            "rfc8785": importlib.metadata.version("rfc8785"),
            "postgresql": server_version,
        }

        case = make_case(run_token)
        seed_case(engine, case)
        rollback_points = ("domain_writes", "event", "workflow_binding", "enqueue")
        rollback_evidence: dict[str, Any] = {}
        for failure_point in rollback_points:
            try:
                with engine.begin() as connection:
                    apply_command(connection, client, case, fail_at=failure_point)
            except InjectedFailure as failure:
                assert str(failure) == failure_point
            else:
                raise AssertionError(f"failure point {failure_point} was not injected")
            rollback_evidence[failure_point] = assert_rollback(engine, case)

        try:
            with engine.begin() as connection:
                apply_command(connection, client, case)
            raise RuntimeError("simulated post-commit receipt drop")
        except RuntimeError as failure:
            if str(failure) != "simulated post-commit receipt drop":
                raise
        with engine.begin() as connection:
            replay_result = apply_command(connection, client, case)
        stored_result = verify_committed(engine, case)
        assert replay_result == stored_result
        workflow_result = wait_for_workflow(client, case["workflow_id"])
        assert workflow_result == case["request_digest"]

        changed_case = dict(case)
        changed_request = json.loads(json.dumps(case["request"]))
        changed_request["request"]["outcome"] = "continue_required"
        changed_case["request"] = changed_request
        changed_case["request_digest"] = digest_request(changed_request)
        try:
            with engine.begin() as connection:
                apply_command(connection, client, changed_case)
        except IdentityDigestConflict:
            pass
        else:
            raise AssertionError("same identity with a different digest was accepted")
        assert verify_committed(engine, case) == stored_result

        async_case = make_case(run_token, "-async")
        asyncio.run(async_rollback_probe(async_engine, engine, client, async_case))
        async_evidence = assert_rollback(engine, async_case)
        report.update(
            {
                "request_digest": case["request_digest"],
                "command_id": case["command_id"],
                "operation_id": case["operation_id"],
                "workflow_id": case["workflow_id"],
                "application_version": APP_VERSION,
                "workflow_name": WORKFLOW_NAME,
                "queue_name": QUEUE_NAME,
                "rollback_points": rollback_evidence,
                "receipt_loss_replay": {
                    "replay_result_equals_stored_result": True,
                    "task_version": f"{BASE_TASK_VERSION}->{BASE_TASK_VERSION + 1}",
                    "agent_run_version": f"{BASE_RUN_VERSION}->{BASE_RUN_VERSION + 1}",
                    "agent_run_status": "succeeded",
                    "agent_run_outcome": "submitted",
                    "operation_count": 1,
                    "event_count": 1,
                    "workflow_binding_count": 1,
                    "dbos_public_status": "SUCCESS",
                    "workflow_result_matches_digest": True,
                    "stored_result": stored_result,
                },
                "same_identity_different_digest": {
                    "original_digest": case["request_digest"],
                    "conflicting_digest": changed_case["request_digest"],
                    "rejected": True,
                    "committed_result_unchanged": True,
                },
                "async_run_sync": {
                    "command_id": async_case["command_id"],
                    "operation_id": async_case["operation_id"],
                    "workflow_id": async_case["workflow_id"],
                    "request_digest": async_case["request_digest"],
                    "after_enqueue_rollback": async_evidence,
                },
                "exit_conclusion": "PASS for the tested same-PostgreSQL-schema-separated transaction seam",
                "status": "passed",
            }
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        if client is not None:
            client.destroy()
        if runtime_constructed:
            DBOS.destroy()
        asyncio.run(async_engine.dispose())
        engine.dispose()


if __name__ == "__main__":
    main()
