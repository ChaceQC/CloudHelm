"""Delivery-owned immutable build intentions; physical facts live in the event log."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    String, Table, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

build_runs = Table(
    "build_runs", metadata,
    Column("build_run_id", String(160), primary_key=True),
    Column("operation_id", String(160), nullable=False, unique=True),
    Column("command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_build_runs_command", deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("candidate_id", String(160), nullable=False),
    Column("expected_task_version", BigInteger, nullable=False),
    Column("accepted_task_version", BigInteger, nullable=False),
    Column("control_revision", BigInteger, nullable=False),
    Column("input_validity_revision", BigInteger, nullable=False),
    Column("input_set_key", String(71), ForeignKey(
        "cloudhelm.task_reference_records.reference_key", name="fk_build_runs_input_set",
    ), nullable=False),
    Column("request_json", JSONB, nullable=False),
    Column("command_request_digest", String(71), nullable=False),
    Column("request_digest", String(71), nullable=False),
    Column("fixed_inputs_json", JSONB, nullable=False),
    Column("build_input_digest", String(71), nullable=False),
    Column("authorization_decision_id", String(160), ForeignKey(
        "cloudhelm.audit_records.decision_id", name="fk_build_runs_authorization",
    ), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["project_id", "task_id"],
                         ["cloudhelm.tasks.project_id", "cloudhelm.tasks.task_id"], name="fk_build_runs_task"),
    ForeignKeyConstraint(["candidate_id", "project_id", "task_id"],
                         ["cloudhelm.workspace_candidates.candidate_id", "cloudhelm.workspace_candidates.project_id",
                          "cloudhelm.workspace_candidates.task_id"], name="fk_build_runs_candidate_owner"),
    ForeignKeyConstraint(["task_id", "input_validity_revision"],
                         ["cloudhelm.task_inputs.task_id", "cloudhelm.task_inputs.input_validity_revision"],
                         name="fk_build_runs_task_input_revision"),
    CheckConstraint("build_run_id = 'build-' || command_id AND operation_id = 'build-operation-' || command_id",
                    name="operation_identity"),
    CheckConstraint("expected_task_version BETWEEN 1 AND 9007199254740990 "
                    "AND accepted_task_version = expected_task_version + 1", name="task_version"),
    CheckConstraint("control_revision BETWEEN 0 AND 9007199254740991 "
                    "AND input_validity_revision BETWEEN 1 AND 9007199254740991", name="task_revisions"),
    CheckConstraint("command_request_digest ~ '^sha256:[0-9a-f]{64}$' "
                    "AND request_digest ~ '^sha256:[0-9a-f]{64}$' "
                    "AND build_input_digest ~ '^sha256:[0-9a-f]{64}$'", name="digests"),
    CheckConstraint("jsonb_typeof(request_json) = 'object' AND octet_length(request_json::text) <= 65536 "
                    "AND (request_json ->> 'candidate_id') IS NOT DISTINCT FROM candidate_id "
                    "AND (request_json ->> 'expected_version') IS NOT DISTINCT FROM expected_task_version::text "
                    "AND (request_json ->> 'expected_control_revision') IS NOT DISTINCT FROM control_revision::text "
                    "AND (request_json ->> 'expected_input_validity_revision') "
                    "IS NOT DISTINCT FROM input_validity_revision::text", name="request_binding"),
    CheckConstraint("jsonb_typeof(fixed_inputs_json) = 'object' "
                    "AND octet_length(fixed_inputs_json::text) <= 131072 "
                    "AND (fixed_inputs_json #>> '{candidate,candidate_id}') IS NOT DISTINCT FROM candidate_id "
                    "AND (fixed_inputs_json #>> '{candidate,binding,project_id}') IS NOT DISTINCT FROM project_id "
                    "AND (fixed_inputs_json #>> '{candidate,binding,task_id}') IS NOT DISTINCT FROM task_id "
                    "AND (fixed_inputs_json -> 'definition') IS NOT DISTINCT FROM (request_json -> 'definition') "
                    "AND (fixed_inputs_json -> 'source_input_set_ref') "
                    "IS NOT DISTINCT FROM (request_json -> 'input_set_ref')", name="fixed_inputs_binding"),
)
