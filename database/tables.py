"""Maintenance-owned installation provenance and the ordinary startup gate."""

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Integer, SmallInteger, String, Table, func,
)

from database.metadata import metadata

BUSINESS_REVISION = "0020_p2_previews"
POSTGRESQL_VERSION_NUM = 160013

runtime_baseline = Table(
    "runtime_baseline", metadata,
    Column("installation_id", String(160), primary_key=True),
    Column("singleton_key", SmallInteger, nullable=False, unique=True, server_default="1"),
    Column("mode", String(32), nullable=False),
    Column("initialization_operation_id", String(160), nullable=False, unique=True),
    Column("business_revision", String(32), nullable=False),
    Column("application_name", String(160), nullable=False),
    Column("application_version", String(160), nullable=False),
    Column("dbos_sdk_version", String(32), nullable=False),
    Column("dbos_schema", String(63), nullable=False),
    Column("dbos_schema_version", Integer),
    Column("dbos_initialized", Boolean, nullable=False, server_default="false"),
    Column("postgresql_version_num", Integer, nullable=False),
    Column("initialized_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("singleton_key = 1", name="single_installation"),
    CheckConstraint("mode IN ('initializing', 'ready', 'recovery_required')", name="runtime_mode"),
    CheckConstraint(
        "mode <> 'ready' OR (dbos_initialized AND initialized_at IS NOT NULL)",
        name="ready_requires_initialization",
    ),
)
