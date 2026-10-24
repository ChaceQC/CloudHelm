"""Delivery-owned immutable objects, target facts and a single binding control head."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Table, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


def _immutable(name, key):
    return Table(name, metadata,
        Column(key, String(160), primary_key=True),
        Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
        Column("digest", String(71), nullable=False),
        Column("value_json", JSONB, nullable=False),
        Column("command_id", String(160), ForeignKey("cloudhelm.commands.command_id",
            deferrable=True, initially="DEFERRED"), nullable=False),
        Column("authorization_decision_id", String(160), ForeignKey("cloudhelm.audit_records.decision_id"), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        CheckConstraint("digest ~ '^sha256:[0-9a-f]{64}$'", name="digest"),
        CheckConstraint("jsonb_typeof(value_json) = 'object' AND octet_length(value_json::text) <= 131072",
                        name="bounded_payload"),
    )


releases = _immutable("releases", "release_id")
environment_configs = _immutable("environment_configs", "config_revision_id")
deployment_plans = _immutable("deployment_plans", "plan_id")
deployment_approvals = _immutable("deployment_approvals", "plan_id")

delivery_targets = Table("delivery_targets", metadata,
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), primary_key=True),
    Column("target_id", String(160), primary_key=True),
    Column("installation_id", String(160), nullable=False),
    Column("registration_json", JSONB, nullable=False),
    Column("digest", String(71), nullable=False),
    CheckConstraint("octet_length(registration_json::text) <= 16384", name="bounded_registration"),
)

environment_bindings = Table("environment_bindings", metadata,
    Column("binding_id", String(160), primary_key=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("environment_id", String(160), nullable=False),
    Column("value_json", JSONB, nullable=False),
    Column("digest", String(71), nullable=False),
    Column("environment_revision", BigInteger, nullable=False, server_default="0"),
    Column("config_revision", BigInteger, nullable=False, server_default="0"),
    Column("release_id", String(160), ForeignKey("cloudhelm.releases.release_id")),
    Column("config_revision_id", String(160), ForeignKey("cloudhelm.environment_configs.config_revision_id")),
    Column("active_operation_id", String(160)),
    UniqueConstraint("project_id", "environment_id", name="uq_environment_bindings_logical_environment"),
    CheckConstraint("environment_revision BETWEEN 0 AND 9007199254740991 "
                    "AND config_revision BETWEEN 0 AND 9007199254740991", name="revisions"),
)

target_observations = Table("delivery_target_observations", metadata,
    Column("observation_id", String(160), primary_key=True),
    Column("binding_id", String(160), ForeignKey("cloudhelm.environment_bindings.binding_id"), nullable=False),
    Column("digest", String(71), nullable=False),
    Column("value_json", JSONB, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("octet_length(value_json::text) <= 32768", name="bounded_observation"),
)

environment_revisions = Table("environment_revisions", metadata,
    Column("binding_id", String(160), ForeignKey("cloudhelm.environment_bindings.binding_id"), primary_key=True),
    Column("environment_revision", BigInteger, primary_key=True),
    Column("plan_id", String(160), ForeignKey("cloudhelm.deployment_plans.plan_id"), nullable=False),
    Column("operation_id", String(160), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
