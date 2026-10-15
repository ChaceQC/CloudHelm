"""One immutable authority registration per Project; locations stay outside the row."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Table,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


project_git_sources = Table(
    "project_git_sources", metadata,
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id", name="fk_git_sources_project"),
           primary_key=True),
    Column("source_id", String(160), nullable=False, unique=True),
    Column("source_revision", BigInteger, nullable=False),
    Column("source_json", JSONB, nullable=False),
    Column("source_digest", String(71), nullable=False),
    Column("registered_by_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_git_sources_command", deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("authorization_decision_id", String(160),
           ForeignKey("cloudhelm.audit_records.decision_id", name="fk_git_sources_authorization"), nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("project_id", "source_id", "source_revision", name="uq_project_git_source_binding"),
    CheckConstraint("source_revision BETWEEN 0 AND 9007199254740991", name="source_revision"),
    CheckConstraint("source_digest ~ '^sha256:[0-9a-f]{64}$'", name="source_digest"),
    CheckConstraint(
        "jsonb_typeof(source_json) = 'object' AND octet_length(source_json::text) <= 16384",
        name="source_bounded",
    ),
    CheckConstraint(
        "(source_json ->> 'project_id') IS NOT DISTINCT FROM project_id AND "
        "(source_json ->> 'source_id') IS NOT DISTINCT FROM source_id AND "
        "(source_json ->> 'source_revision') IS NOT DISTINCT FROM source_revision::text",
        name="source_identity",
    ),
)
