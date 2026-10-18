"""Mutable Workspace development environment ownership and operation ledger."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, String, Table, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


workspace_development_environments = Table(
    "workspace_development_environments", metadata,
    Column("environment_id", String(160), primary_key=True),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("workspace_id", String(160), nullable=False),
    Column("work_item_id", String(160), nullable=False),
    Column("owner_user_id", String(160), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("source_revision", BigInteger, nullable=False),
    Column("workspace_revision", BigInteger, nullable=False),
    Column("write_generation", BigInteger, nullable=False),
    Column("binding_json", JSONB, nullable=False),
    Column("binding_digest", String(71), nullable=False),
    Column("profile_revision", String(64), nullable=False),
    Column("storage_ref_json", JSONB, nullable=False),
    Column("toolchain_json", JSONB, nullable=False),
    Column("toolchain_digest", String(71), nullable=False),
    Column("source_manifest_digest", String(71), nullable=False),
    Column("original_lock_digest", String(71), nullable=False),
    Column("dependency_cache_key", String(71), nullable=False),
    Column("migration_revision", String(96), nullable=False),
    Column("data_revision", String(96), nullable=False),
    Column("data_generation", BigInteger, nullable=False),
    Column("environment_revision", BigInteger, nullable=False),
    Column("state", String(16), nullable=False),
    Column("runtime_fact_json", JSONB),
    Column("health_probe_json", JSONB),
    Column("ready_probe_json", JSONB),
    Column("stop_fact_json", JSONB),
    Column("created_by_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_workspace_development_environments_command",
        deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("authorization_decision_id", String(160), ForeignKey(
        "cloudhelm.audit_records.decision_id", name="fk_workspace_development_environments_authorization",
    ), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["workspace_id", "project_id", "task_id", "work_item_id", "owner_user_id", "source_id", "source_revision"],
        ["cloudhelm.workspaces.workspace_id", "cloudhelm.workspaces.project_id", "cloudhelm.workspaces.task_id",
         "cloudhelm.workspaces.work_item_id", "cloudhelm.workspaces.owner_user_id", "cloudhelm.workspaces.source_id",
         "cloudhelm.workspaces.source_revision"], name="fk_workspace_development_environments_workspace_owner",
    ),
    UniqueConstraint("environment_id", "project_id", "task_id", "workspace_id",
                     name="uq_workspace_development_environment_scope"),
    CheckConstraint("environment_id ~ '^dev-env-[0-9a-f]{32}$'", name="environment_id"),
    CheckConstraint("state IN ('preparing', 'ready', 'suspended', 'failed', 'disposed')", name="state"),
    CheckConstraint("profile_revision = 'notes-backend-dev-r1'", name="profile_revision"),
    CheckConstraint("source_revision BETWEEN 0 AND 9007199254740991", name="source_revision"),
    CheckConstraint("workspace_revision BETWEEN 0 AND 9007199254740991", name="workspace_revision"),
    CheckConstraint("write_generation BETWEEN 0 AND 9007199254740991", name="write_gen"),
    CheckConstraint("environment_revision BETWEEN 1 AND 9007199254740991", name="environment_revision"),
    CheckConstraint("data_generation BETWEEN 0 AND 9007199254740991", name="data_generation"),
    CheckConstraint("binding_digest ~ '^sha256:[0-9a-f]{64}$'", name="binding_digest"),
    CheckConstraint("toolchain_digest ~ '^sha256:[0-9a-f]{64}$'", name="toolchain_digest"),
    CheckConstraint("source_manifest_digest ~ '^sha256:[0-9a-f]{64}$'", name="source_digest"),
    CheckConstraint("original_lock_digest ~ '^sha256:[0-9a-f]{64}$'", name="original_lock_digest"),
    CheckConstraint("dependency_cache_key ~ '^sha256:[0-9a-f]{64}$'", name="dependency_cache_key"),
    CheckConstraint(
        "jsonb_typeof(binding_json) = 'object' AND octet_length(binding_json::text) <= 16384 "
        "AND (binding_json ->> 'workspace_id') IS NOT DISTINCT FROM workspace_id "
        "AND (binding_json ->> 'project_id') IS NOT DISTINCT FROM project_id "
        "AND (binding_json ->> 'task_id') IS NOT DISTINCT FROM task_id "
        "AND (binding_json ->> 'work_item_id') IS NOT DISTINCT FROM work_item_id "
        "AND (binding_json ->> 'owner_user_id') IS NOT DISTINCT FROM owner_user_id "
        "AND (binding_json ->> 'source_id') IS NOT DISTINCT FROM source_id "
        "AND (binding_json ->> 'source_revision') IS NOT DISTINCT FROM source_revision::text "
        "AND COALESCE((binding_json ->> 'base_commit') ~ '^([0-9a-f]{40}|[0-9a-f]{64})$', false) "
        "AND (binding_json ->> 'workspace_revision') IS NOT DISTINCT FROM workspace_revision::text "
        "AND (binding_json ->> 'write_generation') IS NOT DISTINCT FROM write_generation::text",
        name="binding",
    ),
    CheckConstraint(
        "jsonb_typeof(storage_ref_json) = 'object' AND octet_length(storage_ref_json::text) <= 4096 "
        "AND (storage_ref_json ->> 'purpose') IS NOT DISTINCT FROM 'workspace'",
        name="storage_ref_bounded",
    ),
    CheckConstraint(
        "jsonb_typeof(toolchain_json) = 'object' AND octet_length(toolchain_json::text) <= 8192 "
        "AND (toolchain_json ->> 'artifact_digest') IS NOT DISTINCT FROM toolchain_digest "
        "AND (toolchain_json #>> '{artifact_ref,kind}') IS NOT DISTINCT FROM 'artifact'",
        name="toolchain_identity",
    ),
    CheckConstraint(
        "(state <> 'ready' OR (runtime_fact_json IS NOT NULL "
        "AND (runtime_fact_json ->> 'status') IS NOT DISTINCT FROM 'running' "
        "AND (runtime_fact_json -> 'binding') IS NOT DISTINCT FROM binding_json "
        "AND (runtime_fact_json ->> 'source_manifest_digest') IS NOT DISTINCT FROM source_manifest_digest "
        "AND (runtime_fact_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner' "
        "AND health_probe_json IS NOT NULL AND (health_probe_json ->> 'path') IS NOT DISTINCT FROM '/health' "
        "AND (health_probe_json ->> 'outcome') IS NOT DISTINCT FROM 'passed' "
        "AND (health_probe_json ->> 'process_id') IS NOT DISTINCT FROM (runtime_fact_json ->> 'process_id') "
        "AND (health_probe_json -> 'binding') IS NOT DISTINCT FROM binding_json "
        "AND (health_probe_json ->> 'source_manifest_digest') IS NOT DISTINCT FROM source_manifest_digest "
        "AND (health_probe_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner' "
        "AND ready_probe_json IS NOT NULL AND (ready_probe_json ->> 'path') IS NOT DISTINCT FROM '/ready' "
        "AND (ready_probe_json ->> 'outcome') IS NOT DISTINCT FROM 'passed' "
        "AND (ready_probe_json ->> 'process_id') IS NOT DISTINCT FROM (runtime_fact_json ->> 'process_id') "
        "AND (ready_probe_json -> 'binding') IS NOT DISTINCT FROM binding_json "
        "AND (ready_probe_json ->> 'source_manifest_digest') IS NOT DISTINCT FROM source_manifest_digest "
        "AND (ready_probe_json ->> 'observed_migration_revision') IS NOT DISTINCT FROM migration_revision "
        "AND (ready_probe_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner' "
        "AND (health_probe_json #>> '{runner,runner_id}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_id}') "
        "AND (ready_probe_json #>> '{runner,runner_id}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_id}') "
        "AND (health_probe_json #>> '{runner,runner_generation}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_generation}') "
        "AND (ready_probe_json #>> '{runner,runner_generation}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_generation}'))) AND "
        "(state NOT IN ('suspended', 'disposed') OR (stop_fact_json IS NOT NULL "
        "AND (stop_fact_json ->> 'outcome') IS NOT DISTINCT FROM 'confirmed_stopped' "
        "AND (stop_fact_json -> 'binding') IS NOT DISTINCT FROM binding_json "
        "AND (runtime_fact_json IS NULL OR (runtime_fact_json ->> 'status') IS NOT DISTINCT FROM 'stopped') "
        "AND (stop_fact_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner'))",
        name="state_facts",
    ),
)
Index(
    "uq_workspace_development_environments_open_workspace",
    workspace_development_environments.c.workspace_id,
    unique=True,
    postgresql_where=text("state <> 'disposed'"),
)


workspace_development_environment_operations = Table(
    "workspace_development_environment_operations", metadata,
    Column("operation_id", String(160), primary_key=True),
    Column("environment_id", String(160), nullable=False),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("workspace_id", String(160), nullable=False),
    Column("action", String(16), nullable=False),
    Column("operation_state", String(16), nullable=False, server_default="pending"),
    Column("expected_environment_revision", BigInteger, nullable=False),
    Column("accepted_environment_revision", BigInteger, nullable=False),
    Column("workspace_revision", BigInteger, nullable=False),
    Column("write_generation", BigInteger, nullable=False),
    Column("binding_json", JSONB, nullable=False),
    Column("binding_digest", String(71), nullable=False),
    Column("source_manifest_digest", String(71), nullable=False),
    Column("data_revision", String(96), nullable=False),
    Column("data_generation", BigInteger, nullable=False),
    Column("request_json", JSONB, nullable=False),
    Column("command_request_digest", String(71), nullable=False),
    Column("request_digest", String(71), nullable=False),
    Column("observation_json", JSONB),
    Column("observation_digest", String(71)),
    Column("command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_workspace_development_environment_operations_command",
        deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("authorization_decision_id", String(160), ForeignKey(
        "cloudhelm.audit_records.decision_id", name="fk_workspace_development_environment_operations_authorization",
    ), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("closed_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["environment_id", "project_id", "task_id", "workspace_id"],
        ["cloudhelm.workspace_development_environments.environment_id",
         "cloudhelm.workspace_development_environments.project_id",
         "cloudhelm.workspace_development_environments.task_id",
         "cloudhelm.workspace_development_environments.workspace_id"],
        name="fk_workspace_development_environment_operations_scope",
    ),
    UniqueConstraint("environment_id", "accepted_environment_revision",
                     name="uq_workspace_development_environment_operation_revision"),
    CheckConstraint("operation_id = 'workspace-dev-env-' || action || '-' || command_id", name="op_identity"),
    CheckConstraint("action IN ('prepare', 'suspend', 'resume', 'reset_data', 'dispose')", name="action"),
    CheckConstraint("operation_state IN ('pending', 'unknown', 'succeeded', 'failed')", name="operation_state"),
    CheckConstraint(
        "expected_environment_revision BETWEEN 0 AND 9007199254740990 "
        "AND accepted_environment_revision = expected_environment_revision + 1",
        name="environment_rev",
    ),
    CheckConstraint(
        "(action = 'prepare' AND expected_environment_revision = 0) OR "
        "(action <> 'prepare' AND expected_environment_revision > 0)", name="prepare_rev",
    ),
    CheckConstraint("workspace_revision BETWEEN 0 AND 9007199254740991", name="workspace_rev"),
    CheckConstraint("write_generation BETWEEN 0 AND 9007199254740991", name="write_gen"),
    CheckConstraint("data_generation BETWEEN 0 AND 9007199254740991", name="data_generation"),
    CheckConstraint("binding_digest ~ '^sha256:[0-9a-f]{64}$'", name="binding_digest"),
    CheckConstraint("source_manifest_digest ~ '^sha256:[0-9a-f]{64}$'", name="source_digest"),
    CheckConstraint(
        "command_request_digest ~ '^sha256:[0-9a-f]{64}$' AND request_digest ~ '^sha256:[0-9a-f]{64}$'",
        name="request_digests",
    ),
    CheckConstraint(
        "jsonb_typeof(binding_json) = 'object' AND octet_length(binding_json::text) <= 16384 "
        "AND (binding_json ->> 'workspace_id') IS NOT DISTINCT FROM workspace_id "
        "AND (binding_json ->> 'project_id') IS NOT DISTINCT FROM project_id "
        "AND (binding_json ->> 'task_id') IS NOT DISTINCT FROM task_id "
        "AND (binding_json ->> 'workspace_revision') IS NOT DISTINCT FROM workspace_revision::text "
        "AND (binding_json ->> 'write_generation') IS NOT DISTINCT FROM write_generation::text "
        "AND COALESCE((binding_json ->> 'base_commit') ~ '^([0-9a-f]{40}|[0-9a-f]{64})$', false)",
        name="binding",
    ),
    CheckConstraint(
        "jsonb_typeof(request_json) = 'object' AND octet_length(request_json::text) <= 32768 "
        "AND (request_json ->> 'operation_id') IS NOT DISTINCT FROM operation_id "
        "AND (request_json ->> 'action') IS NOT DISTINCT FROM action "
        "AND (request_json ->> 'environment_id') IS NOT DISTINCT FROM environment_id "
        "AND (request_json -> 'binding') IS NOT DISTINCT FROM binding_json",
        name="request",
    ),
    CheckConstraint(
        "(observation_json IS NULL AND observation_digest IS NULL) OR "
        "(observation_json IS NOT NULL AND observation_digest IS NOT NULL "
        "AND observation_digest ~ '^sha256:[0-9a-f]{64}$' "
        "AND jsonb_typeof(observation_json) = 'object' AND octet_length(observation_json::text) <= 32768 "
        "AND (observation_json ->> 'operation_id') IS NOT DISTINCT FROM operation_id "
        "AND (observation_json ->> 'request_digest') IS NOT DISTINCT FROM request_digest "
        "AND (observation_json ->> 'environment_id') IS NOT DISTINCT FROM environment_id)",
        name="observation",
    ),
    CheckConstraint(
        "(operation_state IN ('pending', 'unknown') AND closed_at IS NULL) OR "
        "(operation_state IN ('succeeded', 'failed') AND closed_at IS NOT NULL AND observation_json IS NOT NULL)",
        name="closure_receipt",
    ),
)
Index(
    "uq_workspace_development_environment_operations_open",
    workspace_development_environment_operations.c.environment_id,
    unique=True,
    postgresql_where=text("operation_state IN ('pending', 'unknown')"),
)
Index(
    "ix_workspace_development_environment_operations_task_state",
    workspace_development_environment_operations.c.task_id,
    workspace_development_environment_operations.c.operation_state,
)
