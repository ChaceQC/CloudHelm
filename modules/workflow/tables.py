"""Business-to-workflow mappings only; DBOS scheduling state is not mirrored."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Table,
    UniqueConstraint, func,
)

from database.metadata import BUSINESS_SCHEMA, metadata

workflow_bindings = Table(
    "workflow_bindings", metadata,
    Column("workflow_id", String(160), primary_key=True),
    Column("command_id", String(160), ForeignKey(
        f"{BUSINESS_SCHEMA}.commands.command_id", deferrable=True, initially="DEFERRED"
    ), nullable=False),
    Column("business_kind", String(32), nullable=False),
    Column("business_id", String(160), nullable=False),
    Column("process_type", String(160), nullable=False),
    Column("advance_revision", BigInteger, nullable=False),
    Column("workflow_name", String(160), nullable=False),
    Column("queue_name", String(160), nullable=False),
    Column("application_name", String(160), nullable=False),
    Column("application_version", String(160), nullable=False),
    Column("request_digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "business_kind", "business_id", "process_type", "advance_revision",
        name="uq_workflow_bindings_business_advance",
    ),
    CheckConstraint("business_kind = 'task'", name="p1_business_kind"),
    CheckConstraint(
        "advance_revision >= 0 AND advance_revision <= 9007199254740991",
        name="advance_revision",
    ),
)
