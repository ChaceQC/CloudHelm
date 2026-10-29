"""Preview instances and atomic one-ticket/one-session authorizations."""

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Table, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


preview_environments = Table(
    "preview_environments", metadata,
    Column("environment_id", String(160), primary_key=True),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("state", String(24), nullable=False),
    Column("entry_origin", String(512), unique=True),
    Column("record_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["project_id", "task_id"], ["cloudhelm.tasks.project_id", "cloudhelm.tasks.task_id"]),
    CheckConstraint("state IN ('preparing','ready','stopping','stopped','failed')", name="state"),
    CheckConstraint("jsonb_typeof(record_json) = 'object' AND octet_length(record_json::text) <= 65536", name="record_bounded"),
    CheckConstraint("(record_json ->> 'environment_id') IS NOT DISTINCT FROM environment_id "
                    "AND (record_json ->> 'project_id') IS NOT DISTINCT FROM project_id "
                    "AND (record_json ->> 'task_id') IS NOT DISTINCT FROM task_id "
                    "AND (record_json ->> 'state') IS NOT DISTINCT FROM state "
                    "AND (record_json ->> 'entry_origin') IS NOT DISTINCT FROM entry_origin", name="record_identity"),
)

preview_authorizations = Table(
    "preview_authorizations", metadata,
    Column("authorization_id", String(160), primary_key=True),
    Column("environment_id", String(160), ForeignKey("cloudhelm.preview_environments.environment_id"), nullable=False),
    Column("subject_id", String(160), nullable=False),
    Column("command_id", String(160), ForeignKey("cloudhelm.commands.command_id", deferrable=True,
                                                 initially="DEFERRED"), nullable=False, unique=True),
    Column("state", String(16), nullable=False),
    Column("ticket_digest", String(64), nullable=False, unique=True),
    Column("session_digest", String(64), unique=True),
    Column("record_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("state IN ('active','revoking','revoked')", name="state"),
    CheckConstraint("jsonb_typeof(record_json) = 'object' AND octet_length(record_json::text) <= 131072", name="record_bounded"),
    CheckConstraint("(record_json ->> 'environment_id') IS NOT DISTINCT FROM environment_id "
                    "AND (record_json ->> 'command_id') IS NOT DISTINCT FROM command_id "
                    "AND (record_json ->> 'state') IS NOT DISTINCT FROM state "
                    "AND (record_json #>> '{binding,authorization_id}') IS NOT DISTINCT FROM authorization_id "
                    "AND (record_json #>> '{binding,subject_id}') IS NOT DISTINCT FROM subject_id", name="record_identity"),
)
Index("uq_preview_authorizations_open", preview_authorizations.c.environment_id, preview_authorizations.c.subject_id,
      unique=True, postgresql_where=text("state IN ('active','revoking')"))
