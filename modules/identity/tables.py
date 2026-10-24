"""Identity-owned tables on the single Hub metadata and transaction."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, LargeBinary, String,
    Table, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from database.metadata import metadata


users = Table(
    "users", metadata,
    Column("user_id", String(160), primary_key=True),
    Column("display_name", String(160), nullable=False),
    Column("status", String(16), nullable=False, server_default="active"),
    Column("revision", BigInteger, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('active', 'disabled')", name="user_status"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="user_revision_positive"),
    CheckConstraint("length(display_name) BETWEEN 1 AND 160", name="user_display_name_length"),
)

device_sessions = Table(
    "device_sessions", metadata,
    Column("session_id", String(160), primary_key=True),
    Column("user_id", String(160), ForeignKey("cloudhelm.users.user_id"), nullable=False),
    Column("token_digest", LargeBinary(32), nullable=False, unique=True),
    Column("issued_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revision", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("octet_length(token_digest) = 32", name="session_digest_length"),
    CheckConstraint("expires_at > issued_at", name="session_valid_interval"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="session_revision_positive"),
)

project_policies = Table(
    "project_policies", metadata,
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), primary_key=True),
    Column("policy_revision", BigInteger, nullable=False, server_default="1"),
    Column("authorization_revision", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("policy_revision BETWEEN 1 AND 9007199254740991", name="policy_revision_positive"),
    CheckConstraint(
        "authorization_revision BETWEEN 1 AND 9007199254740991",
        name="authorization_revision_positive",
    ),
)

role_bindings = Table(
    "role_bindings", metadata,
    Column("binding_id", String(160), primary_key=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("user_id", String(160), ForeignKey("cloudhelm.users.user_id"), nullable=False),
    Column("role", String(32), nullable=False),
    Column("actions", ARRAY(String(48)), nullable=False),
    Column("revision", BigInteger, nullable=False, server_default="1"),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("role IN ('developer', 'reviewer', 'deployment_approver')", name="binding_supported_role"),
    CheckConstraint("cardinality(actions) BETWEEN 1 AND 20", name="binding_action_count"),
    CheckConstraint("array_position(actions, NULL) IS NULL", name="binding_actions_not_null"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="binding_revision_positive"),
    UniqueConstraint("project_id", "user_id", "role", name="uq_role_binding_subject_role"),
)

delegations = Table(
    "delegations", metadata,
    Column("delegation_id", String(160), primary_key=True),
    Column("agent_subject_id", String(160), nullable=False),
    Column("delegator_user_id", String(160), ForeignKey("cloudhelm.users.user_id"), nullable=False),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("actions", ARRAY(String(48)), nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revision", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("expires_at > issued_at", name="delegation_valid_interval"),
    CheckConstraint("cardinality(actions) BETWEEN 1 AND 20", name="delegation_action_count"),
    CheckConstraint("array_position(actions, NULL) IS NULL", name="delegation_actions_not_null"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="delegation_revision_positive"),
)

audit_records = Table(
    "audit_records", metadata,
    Column("decision_id", String(160), primary_key=True),
    Column("audit_session_id", String(160), nullable=False),
    Column("authentication_source", String(32), nullable=False),
    Column("caller_kind", String(16)),
    Column("subject_id", String(160)),
    Column("delegator_id", String(160)),
    Column("device_session_id", String(160), ForeignKey("cloudhelm.device_sessions.session_id")),
    Column("delegation_id", String(160), ForeignKey("cloudhelm.delegations.delegation_id")),
    Column("source_command_id", String(160)),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id")),
    Column("scope_json", JSONB),
    Column("target_json", JSONB),
    Column("action", String(48), nullable=False),
    Column("role", String(32)),
    Column("role_binding_id", String(160), ForeignKey("cloudhelm.role_bindings.binding_id")),
    Column("permission_revision", BigInteger),
    Column("policy_revision", BigInteger),
    Column("resource_revision", BigInteger),
    Column("outcome", String(16), nullable=False),
    Column("reason_code", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("outcome IN ('allowed', 'denied')", name="audit_outcome"),
    CheckConstraint(
        "authentication_source IN ('device_session', 'recorded_command', 'maintenance', 'anonymous')",
        name="audit_authentication_source",
    ),
    CheckConstraint(
        "caller_kind IS NULL OR caller_kind IN ('human', 'agent')", name="audit_caller_kind",
    ),
    CheckConstraint(
        "outcome <> 'allowed' OR (subject_id IS NOT NULL "
        "AND scope_json IS NOT NULL AND target_json IS NOT NULL "
        "AND (authentication_source = 'maintenance' OR (project_id IS NOT NULL "
        "AND permission_revision IS NOT NULL AND policy_revision IS NOT NULL)))",
        name="audit_allowed_identity_bound",
    ),
)
