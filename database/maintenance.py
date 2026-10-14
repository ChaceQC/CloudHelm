"""First-install/same-SDK initialization under a fail-closed platform lock."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from alembic import command
from alembic.config import Config
from dbos import DBOS
from sqlalchemy import inspect, insert, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from database.connection import create_engine_from_settings
from database.metadata import BUSINESS_SCHEMA
from database.permissions import DBOS_RUNTIME_ROLE, apply_runtime_permissions
from database.readiness import RuntimeBaseline, assert_schema_ready, require_maintenance_role
from database.settings import DatabaseSettings
from database.tables import BUSINESS_REVISION, POSTGRESQL_VERSION_NUM, runtime_baseline
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, DBOS_SCHEMA, DBOS_SDK_VERSION

MAINTENANCE_LOCK_KEY = 18_940_388_314_329_393


class MaintenanceError(RuntimeError):
    """A fixed operator-facing reason; credentials and SQL diagnostics stay private."""


@contextmanager
def maintenance_lock(engine: Engine) -> Iterator[Connection]:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        locked = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": MAINTENANCE_LOCK_KEY})
        if not locked:
            raise MaintenanceError("maintenance_lock_unavailable")
        try:
            yield connection
        finally:
            if not connection.invalidated:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MAINTENANCE_LOCK_KEY})


def _check_supported_database(connection: Connection) -> None:
    require_maintenance_role(connection)
    if version("dbos") != DBOS_SDK_VERSION:
        raise MaintenanceError("dbos_sdk_version_unsupported")
    if int(connection.scalar(text("SHOW server_version_num"))) != POSTGRESQL_VERSION_NUM:
        raise MaintenanceError("postgresql_version_unsupported")


def _existing_installation(connection: Connection) -> dict[str, object] | None:
    inspector = inspect(connection)
    if not inspector.has_schema(BUSINESS_SCHEMA):
        if inspector.has_schema(DBOS_SCHEMA):
            raise MaintenanceError("unowned_dbos_schema_present")
        return None
    if not inspector.has_table("runtime_baseline", schema=BUSINESS_SCHEMA):
        raise MaintenanceError("unowned_business_schema_present")
    row = connection.execute(select(runtime_baseline)).mappings().one_or_none()
    if row is None:
        raise MaintenanceError("installation_provenance_missing")
    return dict(row)


def _create_business_schema(engine: Engine, operation_id: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA cloudhelm AUTHORIZATION cloudhelm_migrator")
        config.attributes["connection"] = connection
        command.upgrade(config, BUSINESS_REVISION)
        connection.execute(insert(runtime_baseline).values(
            installation_id=uuid4().hex, mode="initializing",
            initialization_operation_id=operation_id, business_revision=BUSINESS_REVISION,
            application_name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
            dbos_sdk_version=DBOS_SDK_VERSION, dbos_schema=DBOS_SCHEMA,
            dbos_schema_version=None, dbos_initialized=False,
            postgresql_version_num=POSTGRESQL_VERSION_NUM,
        ))


def _resume_matches(row: dict[str, object], operation_id: str) -> None:
    expected = {
        "mode": "initializing", "initialization_operation_id": operation_id,
        "business_revision": BUSINESS_REVISION, "application_name": APPLICATION_NAME,
        "application_version": APPLICATION_VERSION, "dbos_sdk_version": DBOS_SDK_VERSION,
        "dbos_schema": DBOS_SCHEMA, "postgresql_version_num": POSTGRESQL_VERSION_NUM,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise MaintenanceError("initialization_resume_identity_or_baseline_mismatch")


def _initialize_dbos(settings: DatabaseSettings) -> None:
    # DBOS.migrate logs database locators; this dedicated maintenance path suppresses
    # dependency logs and reports a fixed category instead of forwarding exceptions.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        DBOS.migrate(
            settings.url.get_secret_value(), schema=DBOS_SCHEMA,
            application_role=DBOS_RUNTIME_ROLE,
        )
    except Exception:
        raise MaintenanceError("dbos_initialization_failed") from None
    finally:
        logging.disable(previous)


def initialize_database(
    settings: DatabaseSettings, *, operation_id: str | None = None
) -> RuntimeBaseline:
    """Initialize a fresh database, or resume the same recorded initialization."""
    operation_id = uuid4().hex if operation_id is None else operation_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", operation_id):
        raise MaintenanceError("initialization_operation_id_invalid")
    engine = create_engine_from_settings(settings, purpose="maintenance")
    try:
        with maintenance_lock(engine) as locked:
            _check_supported_database(locked)
            existing = _existing_installation(locked)
            if existing is not None and existing["mode"] == "ready":
                return assert_schema_ready(locked)
            if existing is None:
                _create_business_schema(engine, operation_id)
            else:
                _resume_matches(existing, operation_id)
            _initialize_dbos(settings)
            if locked.invalidated:
                raise MaintenanceError("maintenance_lock_connection_lost")
            with engine.begin() as connection:
                apply_runtime_permissions(connection)
                changed = connection.execute(update(runtime_baseline).where(
                    runtime_baseline.c.initialization_operation_id == operation_id,
                    runtime_baseline.c.mode == "initializing",
                ).values(mode="ready", dbos_initialized=True, initialized_at=datetime.now(timezone.utc)))
                if changed.rowcount != 1:
                    raise MaintenanceError("initialization_record_changed")
            return assert_schema_ready(locked)
    except SQLAlchemyError:
        raise MaintenanceError("database_initialization_failed") from None
    finally:
        engine.dispose()
