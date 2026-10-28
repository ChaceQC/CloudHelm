"""Immutable provenance for one isolated original-operation maintenance scope."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, SmallInteger, String, Table, func

from database.metadata import metadata

archive_maintenance_sources = Table(
    "archive_maintenance_sources", metadata,
    Column("operation_id", String(160), primary_key=True),
    Column("singleton_key", SmallInteger, nullable=False, unique=True, server_default="1"),
    Column("installation_id", String(160), ForeignKey("cloudhelm.runtime_baseline.installation_id"), nullable=False),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("plan_id", String(160), ForeignKey("cloudhelm.deployment_plans.plan_id"), nullable=False),
    Column("binding_id", String(160), ForeignKey("cloudhelm.environment_bindings.binding_id"), nullable=False),
    Column("snapshot_digest", String(71), nullable=False),
    Column("isolation_evidence_digest", String(71), nullable=False),
    Column("input_digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("singleton_key = 1", name="single_scope"),
    CheckConstraint("snapshot_digest ~ '^sha256:[0-9a-f]{64}$'", name="snapshot_digest"),
    CheckConstraint("isolation_evidence_digest ~ '^sha256:[0-9a-f]{64}$'", name="isolation_digest"),
    CheckConstraint("input_digest ~ '^sha256:[0-9a-f]{64}$'", name="input_digest"),
)
