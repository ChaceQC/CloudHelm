"""Read-only business baseline and runtime-role checks, with no schema mutation."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from typing import Literal

from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from database.metadata import BUSINESS_SCHEMA
from database.tables import BUSINESS_REVISION, POSTGRESQL_VERSION_NUM, runtime_baseline
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, DBOS_SCHEMA, DBOS_SDK_VERSION

ROLE_NAMES = {"api": "cloudhelm_api", "worker": "cloudhelm_worker", "migrator": "cloudhelm_migrator"}
ROLE_CONNECTION_LIMITS = {"api": 6, "worker": 8, "migrator": 4}


class DatabaseNotReady(RuntimeError):
    """Stable readiness category; never includes driver diagnostics or credentials."""


@dataclass(frozen=True, slots=True)
class RuntimeBaseline:
    installation_id: str
    initialization_operation_id: str
    business_revision: str
    application_name: str
    application_version: str
    dbos_sdk_version: str
    dbos_schema_version: int | None


def require_maintenance_role(connection: Connection) -> None:
    actual = connection.scalar(text("SELECT current_user"))
    if actual != ROLE_NAMES["migrator"]:
        raise DatabaseNotReady("maintenance_role_required")


def assert_schema_ready(connection: Connection) -> RuntimeBaseline:
    """Verify this installation's supported baseline, not a numeric DBOS schema head."""
    try:
        if not inspect(connection).has_table("runtime_baseline", schema=BUSINESS_SCHEMA):
            raise DatabaseNotReady("database_not_initialized")
        row = connection.execute(select(runtime_baseline)).mappings().one_or_none()
        if row is None or row["mode"] != "ready" or not row["dbos_initialized"]:
            raise DatabaseNotReady("database_recovery_gate_closed")
        expected = {
            "business_revision": BUSINESS_REVISION, "application_name": APPLICATION_NAME,
            "application_version": APPLICATION_VERSION, "dbos_sdk_version": DBOS_SDK_VERSION,
            "dbos_schema": DBOS_SCHEMA, "postgresql_version_num": POSTGRESQL_VERSION_NUM,
        }
        if any(row[key] != value for key, value in expected.items()) or version("dbos") != DBOS_SDK_VERSION:
            raise DatabaseNotReady("database_baseline_incompatible")
        context = MigrationContext.configure(connection, opts={"version_table_schema": BUSINESS_SCHEMA})
        if context.get_current_heads() != (BUSINESS_REVISION,):
            raise DatabaseNotReady("business_migration_head_mismatch")
        if not inspect(connection).has_schema(DBOS_SCHEMA):
            raise DatabaseNotReady("dbos_schema_missing")
        actual = int(connection.scalar(text("SHOW server_version_num")))
        if actual != POSTGRESQL_VERSION_NUM:
            raise DatabaseNotReady("postgresql_version_mismatch")
        return RuntimeBaseline(**{key: row[key] for key in RuntimeBaseline.__dataclass_fields__})
    except SQLAlchemyError:
        raise DatabaseNotReady("database_readiness_unavailable") from None


def assert_runtime_ready(
    connection: Connection, *, role: Literal["api", "worker"]
) -> RuntimeBaseline:
    if role not in {"api", "worker"}:
        raise DatabaseNotReady("runtime_role_invalid")
    baseline = assert_schema_ready(connection)
    row = connection.execute(text(
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
        "rolbypassrls, rolconnlimit FROM pg_roles WHERE rolname = current_user"
    )).mappings().one()
    if row["rolname"] != ROLE_NAMES[role] or any(row[key] for key in (
        "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls"
    )) or row["rolconnlimit"] != ROLE_CONNECTION_LIMITS[role]:
        raise DatabaseNotReady("runtime_role_unrestricted")
    can_create = connection.scalar(text(
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE') "
        "OR has_schema_privilege(current_user, 'public', 'CREATE') "
        "OR has_schema_privilege(current_user, 'cloudhelm', 'CREATE') "
        "OR has_schema_privilege(current_user, 'dbos', 'CREATE')"
    ))
    if can_create:
        raise DatabaseNotReady("runtime_ddl_privilege_present")
    return baseline
