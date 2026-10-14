"""Task consumer-side provenance, reference links and immutable producer receipts."""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, String, Table, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


task_fact_sources = Table(
    "task_fact_sources", metadata,
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), primary_key=True),
    Column("source_id", String(160), primary_key=True),
    Column("source_json", JSONB, nullable=False),
    Column("source_digest", String(71), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("authorization_decision_id", String(160), ForeignKey("cloudhelm.audit_records.decision_id"), nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("octet_length(source_json::text) <= 16384", name="source_bounded"),
)

task_reference_records = Table(
    "task_reference_records", metadata,
    Column("reference_key", String(71), primary_key=True),
    Column("project_id", String(160), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("registration_id", String(160), nullable=False, unique=True),
    Column("source_record_id", String(160), nullable=False),
    Column("record_kind", String(32), nullable=False),
    Column("reference_kind", String(32), nullable=False),
    Column("object_id", String(160), nullable=False),
    Column("revision", String(160), nullable=False),
    Column("authority", String(160)),
    Column("source_content_digest", String(71), nullable=False),
    Column("record_digest", String(71), nullable=False),
    Column("record_json", JSONB, nullable=False),
    Column("authorization_decision_id", String(160), ForeignKey("cloudhelm.audit_records.decision_id"), nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["project_id", "source_id"],
        ["cloudhelm.task_fact_sources.project_id", "cloudhelm.task_fact_sources.source_id"],
    ),
    UniqueConstraint("project_id", "reference_kind", "object_id", "revision", "authority",
                     name="uq_task_references_identity", postgresql_nulls_not_distinct=True),
    UniqueConstraint("project_id", "source_id", "source_record_id", name="uq_task_references_source_record"),
    CheckConstraint("octet_length(record_json::text) <= 131072", name="reference_bounded"),
)

task_evidence_links = Table(
    "task_evidence_links", metadata,
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), primary_key=True),
    Column("evidence_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key"), primary_key=True),
    Column("input_validity_revision", BigInteger, primary_key=True),
    Column("input_set_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key"), nullable=False),
    Column("applicability", String(16), nullable=False),
    Column("rule_id", String(160), nullable=False),
    Column("rule_revision", String(160), nullable=False),
    Column("reason_code", String(160), nullable=False),
    CheckConstraint("applicability IN ('valid', 'needs_review', 'superseded')", name="evidence_applicability"),
    CheckConstraint("input_validity_revision BETWEEN 0 AND 9007199254740991", name="evidence_revision"),
)

task_operation_links = Table(
    "task_operation_links", metadata,
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), primary_key=True),
    Column("operation_id", String(160), primary_key=True),
    Column("operation_ref", JSONB, nullable=False),
    Column("owner_kind", String(16), nullable=False),
    Column("owner_id", String(160), nullable=False),
    Column("affects_completion", Boolean, nullable=False),
    Column("attempt_id", String(160), nullable=False),
    Column("executor_id", String(160), nullable=False),
    Column("executor_generation", BigInteger, nullable=False),
    Column("input_set_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key"), nullable=False),
    Column("effect_scope_digest", String(71), nullable=False),
    Column("admitted_control_revision", BigInteger, nullable=False),
    CheckConstraint("owner_kind IN ('task', 'shared', 'independent')", name="operation_owner"),
    CheckConstraint("owner_kind <> 'task' OR owner_id = task_id", name="owned_operation_task"),
    CheckConstraint("executor_generation BETWEEN 0 AND 9007199254740991", name="operation_generation"),
    CheckConstraint("admitted_control_revision BETWEEN 0 AND 9007199254740991", name="operation_control_revision"),
)

task_operation_observations = Table(
    "task_operation_observations", metadata,
    Column("observation_id", String(160), primary_key=True),
    Column("task_id", String(160), nullable=False),
    Column("operation_id", String(160), nullable=False),
    Column("project_id", String(160), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("record_digest", String(71), nullable=False),
    Column("observation_json", JSONB, nullable=False),
    Column("authorization_decision_id", String(160), ForeignKey("cloudhelm.audit_records.decision_id"), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["task_id", "operation_id"],
                         ["cloudhelm.task_operation_links.task_id", "cloudhelm.task_operation_links.operation_id"]),
    ForeignKeyConstraint(["project_id", "source_id"],
                         ["cloudhelm.task_fact_sources.project_id", "cloudhelm.task_fact_sources.source_id"]),
    CheckConstraint("octet_length(observation_json::text) <= 32768", name="observation_bounded"),
)
