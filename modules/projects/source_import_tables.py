"""Immutable source import intents; acceptance is separate from physical publication."""

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


project_source_imports = Table(
    "project_source_imports", metadata,
    Column("operation_id", String(160), primary_key=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id", name="fk_source_import_project"),
           nullable=False, unique=True),
    Column("source_id", String(160), nullable=False, unique=True),
    Column("command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_source_import_command", deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("authorization_decision_id", String(160), ForeignKey(
        "cloudhelm.audit_records.decision_id", name="fk_source_import_authorization",
    ), nullable=False),
    Column("expected_project_revision", BigInteger, nullable=False),
    Column("accepted_project_revision", BigInteger, nullable=False),
    Column("request_json", JSONB, nullable=False),
    Column("command_request_digest", String(71), nullable=False),
    Column("spec_json", JSONB, nullable=False),
    Column("request_digest", String(71), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("expected_project_revision BETWEEN 1 AND 9007199254740990 "
                    "AND accepted_project_revision = expected_project_revision + 1", name="project_revision"),
    CheckConstraint("operation_id = 'source-import-' || command_id AND source_id = 'source-' || command_id",
                    name="operation_identity"),
    CheckConstraint("command_request_digest ~ '^sha256:[0-9a-f]{64}$' "
                    "AND request_digest ~ '^sha256:[0-9a-f]{64}$'", name="request_digests"),
    CheckConstraint("jsonb_typeof(request_json) = 'object' AND octet_length(request_json::text) <= 4096 "
                    "AND (request_json ->> 'reference_revision') IS NOT DISTINCT FROM 'p0-reference-input-set-r1' "
                    "AND (request_json ->> 'expected_project_revision') IS NOT DISTINCT FROM expected_project_revision::text",
                    name="request_binding"),
    CheckConstraint("jsonb_typeof(spec_json) = 'object' AND octet_length(spec_json::text) <= 16384 "
                    "AND (spec_json ->> 'reference_revision') IS NOT DISTINCT FROM 'p0-reference-input-set-r1' "
                    "AND (spec_json #>> '{source,project_id}') IS NOT DISTINCT FROM project_id "
                    "AND (spec_json #>> '{source,source_id}') IS NOT DISTINCT FROM source_id "
                    "AND (spec_json #>> '{source,source_revision}') IS NOT DISTINCT FROM '1'",
                    name="spec_binding"),
)
