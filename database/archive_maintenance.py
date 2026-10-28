"""Fail-closed, one-operation maintenance of the supported 0008 snapshot."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import rfc8785
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, insert, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from database.archive_maintenance_tables import archive_maintenance_sources
from database.connection import create_engine_from_settings
from database.maintenance import MaintenanceError, maintenance_lock
from database.metadata import BUSINESS_SCHEMA
from database.readiness import DatabaseNotReady, require_maintenance_role
from database.settings import DatabaseSettings
from database.tables import POSTGRESQL_VERSION_NUM, runtime_baseline
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_store import read_object
from modules.delivery.deployment_tables import environment_bindings, environment_revisions
from modules.delivery.release_recipe import delivery_digest
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, DBOS_SCHEMA, DBOS_SDK_VERSION
from packages.contracts.p1.delivery_records import EnvironmentBinding

SOURCE_REVISION = "0008_p1_4_remote"
BUSINESS_REVISION = "0011_p1_archive_maintenance"
SOURCE_SCHEMA = "p1-archive-maintenance-source-r1"
PENDING_SCHEMA = "p1-archive-maintenance-pending-r1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ArchiveMaintenanceScope:
    installation_id: str
    operation_id: str
    project_id: str
    plan_id: str
    binding_id: str
    input_digest: str


def _digest(value: dict[str, str]) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _require_maintenance_login(connection: Connection) -> None:
    require_maintenance_role(connection)
    if connection.scalar(text("SELECT session_user")) != "cloudhelm_migrator":
        raise MaintenanceError("archive_maintenance_login_required")


def _baseline(connection: Connection, row, *, installation_id: str, revision: str, mode: str) -> None:
    expected = {
        "installation_id": installation_id, "mode": mode, "business_revision": revision,
        "application_name": "cloudhelm-hub", "application_version": "0.7.0",
        "dbos_sdk_version": "3.2.0", "dbos_schema": "dbos",
        "postgresql_version_num": 160013, "dbos_initialized": True,
    }
    if (APPLICATION_NAME != "cloudhelm-hub" or APPLICATION_VERSION != "0.7.0"
            or DBOS_SDK_VERSION != "3.2.0" or DBOS_SCHEMA != "dbos"
            or POSTGRESQL_VERSION_NUM != 160013 or BUSINESS_REVISION != "0011_p1_archive_maintenance"):
        raise MaintenanceError("archive_maintenance_baseline_unsupported")
    if (row is None or row["initialized_at"] is None
            or any(row[key] != value for key, value in expected.items())):
        raise MaintenanceError("archive_maintenance_baseline_mismatch")
    if version("dbos") != DBOS_SDK_VERSION:
        raise MaintenanceError("archive_maintenance_sdk_mismatch")
    if int(connection.scalar(text("SHOW server_version_num"))) != POSTGRESQL_VERSION_NUM:
        raise MaintenanceError("archive_maintenance_postgresql_mismatch")
    if not inspect(connection).has_schema(DBOS_SCHEMA):
        raise MaintenanceError("archive_maintenance_dbos_schema_missing")
    context = MigrationContext.configure(connection, opts={"version_table_schema": BUSINESS_SCHEMA})
    if context.get_current_heads() != (revision,):
        raise MaintenanceError("archive_maintenance_migration_head_mismatch")


def _original_scope(connection: Connection, operation_id: str, *, require_active: bool) -> dict[str, str]:
    revision = connection.execute(select(environment_revisions).where(
        environment_revisions.c.operation_id == operation_id,
    )).mappings().one_or_none()
    if revision is None:
        raise MaintenanceError("archive_maintenance_original_operation_missing")
    row = connection.execute(select(environment_bindings).where(
        environment_bindings.c.binding_id == revision["binding_id"],
    )).mappings().one_or_none()
    if row is None:
        raise MaintenanceError("archive_maintenance_original_binding_missing")
    try:
        binding = EnvironmentBinding.model_validate(row["value_json"])
        plan = read_object(connection, row["project_id"], "plan", revision["plan_id"])
        approval = read_object(connection, row["project_id"], "approval", revision["plan_id"]).value
        if (binding.binding_id != row["binding_id"] or binding.project_id != row["project_id"]
                or delivery_digest(binding) != row["digest"] or plan.value.binding != binding
                or plan.value.project_id != row["project_id"] or approval.operation_id != operation_id
                or approval.plan_id != plan.object_id or approval.plan_digest != plan.digest
                or approval.binding_id != binding.binding_id
                or approval.config_revision_id != plan.value.configuration.configuration.config_revision_id
                or revision["environment_revision"] != plan.value.expected_state.environment_revision + 1):
            raise ValueError
        if require_active and (
            row["active_operation_id"] != operation_id
            or row["environment_revision"] != revision["environment_revision"]
            or row["release_id"] != plan.value.release_id
            or row["config_revision_id"] != approval.config_revision_id
        ):
            raise ValueError
    except (TaskBoundaryError, ValueError):
        raise MaintenanceError("archive_maintenance_original_scope_invalid") from None
    return {"operation_id": operation_id, "project_id": row["project_id"],
            "plan_id": plan.object_id, "binding_id": binding.binding_id}


def _pending(connection: Connection, expected: dict[str, str]) -> None:
    if not inspect(connection).has_table("archive_maintenance_pending", schema=BUSINESS_SCHEMA):
        raise MaintenanceError("archive_maintenance_pending_missing")
    row = connection.execute(text("""SELECT installation_id, operation_id, snapshot_digest,
        isolation_evidence_digest, pending_digest FROM cloudhelm.archive_maintenance_pending""")).mappings().one_or_none()
    if row is None or dict(row) != expected:
        raise MaintenanceError("archive_maintenance_source_mismatch")


def assert_archive_maintenance(connection: Connection, operation_id: str) -> ArchiveMaintenanceScope:
    """Require the real role, closed gate, current head and immutable original scope."""
    if not isinstance(operation_id, str) or not _IDENTIFIER.fullmatch(operation_id):
        raise MaintenanceError("archive_maintenance_operation_id_invalid")
    try:
        _require_maintenance_login(connection)
        if not inspect(connection).has_table("archive_maintenance_sources", schema=BUSINESS_SCHEMA):
            raise MaintenanceError("archive_maintenance_source_missing")
        row = connection.execute(select(archive_maintenance_sources).where(
            archive_maintenance_sources.c.operation_id == operation_id,
        )).mappings().one_or_none()
        if row is None:
            raise MaintenanceError("archive_maintenance_source_missing")
        baseline = connection.execute(select(runtime_baseline)).mappings().one_or_none()
        _baseline(connection, baseline, installation_id=row["installation_id"],
                  revision=BUSINESS_REVISION, mode="recovery_required")
        fields = {key: row[key] for key in (
            "installation_id", "operation_id", "project_id", "plan_id", "binding_id",
            "snapshot_digest", "isolation_evidence_digest",
        )}
        if (_digest({"schema_revision": SOURCE_SCHEMA, "source_revision": SOURCE_REVISION, **fields})
                != row["input_digest"]):
            raise MaintenanceError("archive_maintenance_source_digest_mismatch")
        original = _original_scope(connection, operation_id, require_active=False)
        if any(fields[key] != value for key, value in original.items()):
            raise MaintenanceError("archive_maintenance_source_mismatch")
        for role in ("cloudhelm_api", "cloudhelm_worker"):
            privileges = connection.execute(text("""SELECT
                has_table_privilege(:role, 'cloudhelm.archive_maintenance_sources', 'SELECT') AS can_read,
                has_table_privilege(:role, 'cloudhelm.archive_maintenance_sources',
                    'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER') AS can_write,
                has_any_column_privilege(:role, 'cloudhelm.archive_maintenance_sources',
                    'INSERT, UPDATE, REFERENCES') AS can_write_column"""), {"role": role}).mappings().one()
            if not privileges["can_read"] or privileges["can_write"] or privileges["can_write_column"]:
                raise MaintenanceError("archive_maintenance_source_privileges_invalid")
        return ArchiveMaintenanceScope(**{key: row[key] for key in ArchiveMaintenanceScope.__dataclass_fields__})
    except SQLAlchemyError:
        raise MaintenanceError("archive_maintenance_unavailable") from None


def _persist_gate(engine: Engine, pending: dict[str, str]) -> ArchiveMaintenanceScope | None:
    """Commit the source and closed gate before resolving or upgrading the operation."""
    installation_id, operation_id = pending["installation_id"], pending["operation_id"]
    gate_needs_closing = False
    try:
        with engine.begin() as connection:
            if not inspect(connection).has_table("runtime_baseline", schema=BUSINESS_SCHEMA):
                raise MaintenanceError("archive_maintenance_baseline_missing")
            baseline = connection.execute(select(runtime_baseline).with_for_update()).mappings().one_or_none()
            if baseline is None or baseline["installation_id"] != installation_id:
                raise MaintenanceError("archive_maintenance_baseline_mismatch")
            if baseline["mode"] == "recovery_required" and baseline["business_revision"] == BUSINESS_REVISION:
                scope = assert_archive_maintenance(connection, operation_id)
                source = connection.execute(select(archive_maintenance_sources).where(
                    archive_maintenance_sources.c.operation_id == operation_id,
                )).mappings().one()
                if (source["snapshot_digest"] != pending["snapshot_digest"]
                        or source["isolation_evidence_digest"] != pending["isolation_evidence_digest"]):
                    raise MaintenanceError("archive_maintenance_source_mismatch")
                return scope
            _require_maintenance_login(connection)
            _baseline(connection, baseline, installation_id=installation_id,
                      revision=SOURCE_REVISION, mode=baseline["mode"])
            has_pending = inspect(connection).has_table("archive_maintenance_pending", schema=BUSINESS_SCHEMA)
            if baseline["mode"] == "recovery_required" and has_pending:
                _pending(connection, pending)
            elif baseline["mode"] in {"ready", "recovery_required"}:
                gate_needs_closing = baseline["mode"] == "ready"
                if has_pending:
                    raise MaintenanceError("archive_maintenance_pending_unexpected")
                if baseline["mode"] == "recovery_required":
                    _original_scope(connection, operation_id, require_active=True)
                connection.exec_driver_sql("""CREATE TABLE cloudhelm.archive_maintenance_pending (
                    installation_id VARCHAR(160) PRIMARY KEY REFERENCES cloudhelm.runtime_baseline(installation_id),
                    operation_id VARCHAR(160) NOT NULL, snapshot_digest VARCHAR(71) NOT NULL,
                    isolation_evidence_digest VARCHAR(71) NOT NULL, pending_digest VARCHAR(71) NOT NULL
                )""")
                connection.exec_driver_sql("""REVOKE ALL ON cloudhelm.archive_maintenance_pending
                    FROM PUBLIC, cloudhelm_api, cloudhelm_worker, cloudhelm_dbos_runtime""")
                connection.execute(text("""INSERT INTO cloudhelm.archive_maintenance_pending
                    (installation_id, operation_id, snapshot_digest, isolation_evidence_digest, pending_digest)
                    VALUES (:installation_id, :operation_id, :snapshot_digest, :isolation_evidence_digest,
                            :pending_digest)"""), pending)
                if baseline["mode"] == "ready":
                    connection.execute(update(runtime_baseline).where(
                        runtime_baseline.c.installation_id == installation_id,
                    ).values(mode="recovery_required"))
            else:
                raise MaintenanceError("archive_maintenance_gate_invalid")
        return None
    except (SQLAlchemyError, DatabaseNotReady, MaintenanceError) as failure:
        if gate_needs_closing:
            try:
                with engine.begin() as connection:
                    _require_maintenance_login(connection)
                    changed = connection.execute(update(runtime_baseline).where(
                        runtime_baseline.c.installation_id == installation_id,
                        runtime_baseline.c.mode == "ready",
                        runtime_baseline.c.business_revision == SOURCE_REVISION,
                    ).values(mode="recovery_required"))
                    if changed.rowcount != 1:
                        current_mode = connection.scalar(select(runtime_baseline.c.mode).where(
                            runtime_baseline.c.installation_id == installation_id,
                        ))
                        if current_mode != "recovery_required":
                            raise MaintenanceError("archive_maintenance_gate_unconfirmed")
            except (SQLAlchemyError, DatabaseNotReady):
                raise MaintenanceError("archive_maintenance_gate_unconfirmed") from None
        if isinstance(failure, MaintenanceError):
            raise
        raise MaintenanceError("archive_maintenance_unavailable") from None


def prepare_archive_maintenance(
    settings: DatabaseSettings, *, expected_installation_id: str, operation_id: str,
    snapshot_digest: str, isolation_evidence_digest: str,
) -> ArchiveMaintenanceScope:
    """Persist the closed gate and source first, then upgrade only that source."""
    if (any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value)
            for value in (expected_installation_id, operation_id))
            or any(not isinstance(value, str) or not _DIGEST.fullmatch(value)
                   for value in (snapshot_digest, isolation_evidence_digest))):
        raise MaintenanceError("archive_maintenance_input_invalid")
    pending = {"installation_id": expected_installation_id, "operation_id": operation_id,
               "snapshot_digest": snapshot_digest, "isolation_evidence_digest": isolation_evidence_digest}
    pending["pending_digest"] = _digest({"schema_revision": PENDING_SCHEMA, **pending})
    engine = create_engine_from_settings(settings, purpose="maintenance")
    try:
        with maintenance_lock(engine) as locked:
            scope = _persist_gate(engine, pending)
            if scope is not None:
                return scope
            locked.scalar(text("SELECT 1"))
            with engine.begin() as connection:
                _require_maintenance_login(connection)
                baseline = connection.execute(select(runtime_baseline)).mappings().one_or_none()
                _baseline(connection, baseline, installation_id=expected_installation_id,
                          revision=SOURCE_REVISION, mode="recovery_required")
                _pending(connection, pending)
                original = _original_scope(connection, operation_id, require_active=True)
                fields = {"installation_id": expected_installation_id, **original,
                          "snapshot_digest": snapshot_digest, "isolation_evidence_digest": isolation_evidence_digest}
                input_digest = _digest({"schema_revision": SOURCE_SCHEMA, "source_revision": SOURCE_REVISION, **fields})
                config = Config()
                config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
                config.attributes["connection"] = connection
                command.upgrade(config, BUSINESS_REVISION)
                connection.execute(insert(archive_maintenance_sources).values(**fields, input_digest=input_digest))
                connection.execute(update(runtime_baseline).where(
                    runtime_baseline.c.installation_id == expected_installation_id,
                    runtime_baseline.c.mode == "recovery_required",
                    runtime_baseline.c.business_revision == SOURCE_REVISION,
                ).values(business_revision=BUSINESS_REVISION))
                connection.exec_driver_sql("DROP TABLE cloudhelm.archive_maintenance_pending")
                locked.scalar(text("SELECT 1"))
                return assert_archive_maintenance(connection, operation_id)
    except (SQLAlchemyError, DatabaseNotReady):
        raise MaintenanceError("archive_maintenance_unavailable") from None
    finally:
        engine.dispose()
