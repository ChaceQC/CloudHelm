"""Narrow real-database checks for P1 initialization, roles, and transaction ownership."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from dbos import DBOSClient, DBOSPortableJSONSerializer
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import DBAPIError

from database.connection import create_business_pools, create_engine_from_settings
from database.maintenance import MaintenanceError, initialize_database, maintenance_lock
from database.metadata import metadata
from database.models import load_business_metadata
from database.readiness import assert_runtime_ready, assert_schema_ready, require_maintenance_role
from database.tables import runtime_baseline
from database.uow import UnitOfWork
from modules.workflow.version import APPLICATION_NAME, DBOS_SCHEMA
from scripts.p1.database_fixture import DatabaseFixture, database_fixture


class DatabaseCheckFailure(AssertionError):
    pass


def _expect_denied(engine, statement: str) -> None:
    with UnitOfWork(engine) as uow:
        try:
            with uow.connection.begin_nested():
                uow.connection.exec_driver_sql(statement)
        except DBAPIError as failure:
            if getattr(failure.orig, "sqlstate", None) != "42501":
                raise DatabaseCheckFailure("permission_probe_wrong_sqlstate") from None
        else:
            raise DatabaseCheckFailure("forbidden_statement_was_allowed")


def _runtime_role(fixture: DatabaseFixture, role: str) -> dict[str, object]:
    pools = create_business_pools(fixture.settings(role))
    try:
        for engine in (pools.normal, pools.control):
            with UnitOfWork(engine) as uow:
                assert_runtime_ready(uow.connection, role=role)
        forbidden = (
            "CREATE SCHEMA p1_forbidden",
            "CREATE TABLE cloudhelm.p1_forbidden (value integer)",
            "CREATE ROLE p1_forbidden",
            "ALTER TABLE cloudhelm.tasks ADD COLUMN p1_forbidden boolean",
            "UPDATE cloudhelm.commands SET status_code = status_code WHERE false",
            "DELETE FROM cloudhelm.audit_records WHERE false",
            "TRUNCATE TABLE cloudhelm.task_completion_reports CASCADE",
            "UPDATE cloudhelm.runtime_baseline SET mode = mode WHERE false",
            "UPDATE cloudhelm.task_reference_records SET record_digest = record_digest WHERE false",
            "UPDATE cloudhelm.task_fact_sources SET source_digest = source_digest WHERE false",
            "SET ROLE cloudhelm_migrator",
        )
        for statement in forbidden:
            _expect_denied(pools.normal, statement)
        client = DBOSClient(
            system_database_engine=pools.normal, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False,
        )
        try:
            if client.list_workflows(limit=1, load_input=False, load_output=False):
                raise DatabaseCheckFailure("fresh_database_contains_workflows")
        finally:
            client.destroy()
        return {"role": role, "normal_pool": pools.normal.pool.size(),
                "control_pool": pools.control.pool.size(), "denials": len(forbidden),
                "dbos_public_query": "empty"}
    finally:
        pools.dispose()


def _maintenance(fixture: DatabaseFixture) -> dict[str, object]:
    settings = fixture.settings("migrator")
    first = fixture.baseline
    repeated = initialize_database(settings)
    if first != repeated:
        raise DatabaseCheckFailure("initialization_replay_changed_baseline")
    engine = create_engine_from_settings(settings, purpose="maintenance")
    try:
        with maintenance_lock(engine):
            try:
                initialize_database(settings)
            except MaintenanceError as failure:
                if str(failure) != "maintenance_lock_unavailable":
                    raise DatabaseCheckFailure("unexpected_maintenance_lock_result") from None
            else:
                raise DatabaseCheckFailure("concurrent_maintenance_was_allowed")
        try:
            with UnitOfWork(engine) as uow:
                require_maintenance_role(uow.connection)
                uow.connection.execute(update(runtime_baseline).values(mode="recovery_required"))
                raise DatabaseCheckFailure("deliberate_rollback")
        except DatabaseCheckFailure as failure:
            if str(failure) != "deliberate_rollback":
                raise
        with UnitOfWork(engine) as uow:
            if assert_schema_ready(uow.connection) != first:
                raise DatabaseCheckFailure("unit_of_work_did_not_rollback")
            tables = inspect(uow.connection).get_table_names(schema="cloudhelm")
            if set(tables) != {table.name for table in metadata.tables.values()} | {"alembic_version"}:
                raise DatabaseCheckFailure("static_migration_table_set_mismatch")
            if uow.connection.scalar(select(runtime_baseline.c.dbos_schema_version)) is not None:
                raise DatabaseCheckFailure("unsupported_exact_dbos_schema_version_claim")
        return {"same_initialization_replayed": True, "maintenance_lock_rejected": True,
                "unit_of_work_rollback": True, "business_tables": len(tables) - 1,
                "dbos_schema_version": None}
    finally:
        engine.dispose()


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    load_business_metadata()
    print(json.dumps({"status": "running", "method": "p1-database-r1", "started_at": started_at}), flush=True)
    try:
        with database_fixture() as fixture:
            report = {"fixture_id": fixture.project_name, "baseline": asdict(fixture.baseline),
                      "maintenance": _maintenance(fixture),
                      "runtime_roles": [_runtime_role(fixture, role) for role in ("api", "worker")]}
        print(json.dumps({"status": "passed", "method": "p1-database-r1", "started_at": started_at,
                          "finished_at": datetime.now(timezone.utc).isoformat(), "cleanup": "complete",
                          "scope": "WSL initialization and role checks; no worker or Task acceptance",
                          **report}, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as failure:
        safe = str(failure) if type(failure).__module__.startswith(("database.", "scripts.p1.")) else type(failure).__name__
        print(json.dumps({"status": "failed", "method": "p1-database-r1", "reason": safe,
                          "diagnostic": getattr(failure, "public_diagnostic", None),
                          "finished_at": datetime.now(timezone.utc).isoformat()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
