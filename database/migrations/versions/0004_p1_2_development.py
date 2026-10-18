"""Mutable Workspace development environment ledger; isolated installs only."""

from alembic import op

revision = "0004_p1_2_development"
down_revision = "0003_p1_2_builds"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE cloudhelm.workspace_development_environments (
    environment_id VARCHAR(160) NOT NULL,
    project_id VARCHAR(160) NOT NULL,
    task_id VARCHAR(160) NOT NULL,
    workspace_id VARCHAR(160) NOT NULL,
    work_item_id VARCHAR(160) NOT NULL,
    owner_user_id VARCHAR(160) NOT NULL,
    source_id VARCHAR(160) NOT NULL,
    source_revision BIGINT NOT NULL,
    workspace_revision BIGINT NOT NULL,
    write_generation BIGINT NOT NULL,
    binding_json JSONB NOT NULL,
    binding_digest VARCHAR(71) NOT NULL,
    profile_revision VARCHAR(64) NOT NULL,
    storage_ref_json JSONB NOT NULL,
    toolchain_json JSONB NOT NULL,
    toolchain_digest VARCHAR(71) NOT NULL,
    source_manifest_digest VARCHAR(71) NOT NULL,
    original_lock_digest VARCHAR(71) NOT NULL,
    dependency_cache_key VARCHAR(71) NOT NULL,
    migration_revision VARCHAR(96) NOT NULL,
    data_revision VARCHAR(96) NOT NULL,
    data_generation BIGINT NOT NULL,
    environment_revision BIGINT NOT NULL,
    state VARCHAR(16) NOT NULL,
    runtime_fact_json JSONB,
    health_probe_json JSONB,
    ready_probe_json JSONB,
    stop_fact_json JSONB,
    created_by_command_id VARCHAR(160) NOT NULL,
    authorization_decision_id VARCHAR(160) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_workspace_development_environments PRIMARY KEY (environment_id),
    CONSTRAINT fk_workspace_development_environments_command FOREIGN KEY(created_by_command_id) REFERENCES cloudhelm.commands (command_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_workspace_development_environments_created_by_command_id UNIQUE (created_by_command_id),
    CONSTRAINT fk_workspace_development_environments_authorization FOREIGN KEY(authorization_decision_id) REFERENCES cloudhelm.audit_records (decision_id),
    CONSTRAINT fk_workspace_development_environments_workspace_owner FOREIGN KEY(workspace_id, project_id, task_id, work_item_id, owner_user_id, source_id, source_revision) REFERENCES cloudhelm.workspaces (workspace_id, project_id, task_id, work_item_id, owner_user_id, source_id, source_revision),
    CONSTRAINT uq_workspace_development_environment_scope UNIQUE (environment_id, project_id, task_id, workspace_id),
    CONSTRAINT ck_workspace_development_environments_environment_id CHECK (environment_id ~ '^dev-env-[0-9a-f]{32}$'),
    CONSTRAINT ck_workspace_development_environments_state CHECK (state IN ('preparing', 'ready', 'suspended', 'failed', 'disposed')),
    CONSTRAINT ck_workspace_development_environments_profile_revision CHECK (profile_revision = 'notes-backend-dev-r1'),
    CONSTRAINT ck_workspace_development_environments_source_revision CHECK (source_revision BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environments_workspace_revision CHECK (workspace_revision BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environments_write_gen CHECK (write_generation BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environments_environment_revision CHECK (environment_revision BETWEEN 1 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environments_data_generation CHECK (data_generation BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environments_binding_digest CHECK (binding_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environments_toolchain_digest CHECK (toolchain_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environments_source_digest CHECK (source_manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environments_original_lock_digest CHECK (original_lock_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environments_dependency_cache_key CHECK (dependency_cache_key ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environments_binding CHECK (
        jsonb_typeof(binding_json) = 'object' AND octet_length(binding_json::text) <= 16384
        AND (binding_json ->> 'workspace_id') IS NOT DISTINCT FROM workspace_id
        AND (binding_json ->> 'project_id') IS NOT DISTINCT FROM project_id
        AND (binding_json ->> 'task_id') IS NOT DISTINCT FROM task_id
        AND (binding_json ->> 'work_item_id') IS NOT DISTINCT FROM work_item_id
        AND (binding_json ->> 'owner_user_id') IS NOT DISTINCT FROM owner_user_id
        AND (binding_json ->> 'source_id') IS NOT DISTINCT FROM source_id
        AND (binding_json ->> 'source_revision') IS NOT DISTINCT FROM source_revision::text
        AND COALESCE((binding_json ->> 'base_commit') ~ '^([0-9a-f]{40}|[0-9a-f]{64})$', false)
        AND (binding_json ->> 'workspace_revision') IS NOT DISTINCT FROM workspace_revision::text
        AND (binding_json ->> 'write_generation') IS NOT DISTINCT FROM write_generation::text),
    CONSTRAINT ck_workspace_development_environments_storage_ref_bounded CHECK (
        jsonb_typeof(storage_ref_json) = 'object' AND octet_length(storage_ref_json::text) <= 4096
        AND (storage_ref_json ->> 'purpose') IS NOT DISTINCT FROM 'workspace'),
    CONSTRAINT ck_workspace_development_environments_toolchain_identity CHECK (
        jsonb_typeof(toolchain_json) = 'object' AND octet_length(toolchain_json::text) <= 8192
        AND (toolchain_json ->> 'artifact_digest') IS NOT DISTINCT FROM toolchain_digest
        AND (toolchain_json #>> '{artifact_ref,kind}') IS NOT DISTINCT FROM 'artifact'),
    CONSTRAINT ck_workspace_development_environments_state_facts CHECK (
        (state <> 'ready' OR (runtime_fact_json IS NOT NULL
        AND (runtime_fact_json ->> 'status') IS NOT DISTINCT FROM 'running'
        AND (runtime_fact_json -> 'binding') IS NOT DISTINCT FROM binding_json
        AND (runtime_fact_json ->> 'source_manifest_digest') IS NOT DISTINCT FROM source_manifest_digest
        AND (runtime_fact_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner'
        AND health_probe_json IS NOT NULL AND (health_probe_json ->> 'path') IS NOT DISTINCT FROM '/health'
        AND (health_probe_json ->> 'outcome') IS NOT DISTINCT FROM 'passed'
        AND (health_probe_json ->> 'process_id') IS NOT DISTINCT FROM (runtime_fact_json ->> 'process_id')
        AND (health_probe_json -> 'binding') IS NOT DISTINCT FROM binding_json
        AND (health_probe_json ->> 'source_manifest_digest') IS NOT DISTINCT FROM source_manifest_digest
        AND (health_probe_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner'
        AND ready_probe_json IS NOT NULL AND (ready_probe_json ->> 'path') IS NOT DISTINCT FROM '/ready'
        AND (ready_probe_json ->> 'outcome') IS NOT DISTINCT FROM 'passed'
        AND (ready_probe_json ->> 'process_id') IS NOT DISTINCT FROM (runtime_fact_json ->> 'process_id')
        AND (ready_probe_json -> 'binding') IS NOT DISTINCT FROM binding_json
        AND (ready_probe_json ->> 'source_manifest_digest') IS NOT DISTINCT FROM source_manifest_digest
        AND (ready_probe_json ->> 'observed_migration_revision') IS NOT DISTINCT FROM migration_revision
        AND (ready_probe_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner'
        AND (health_probe_json #>> '{runner,runner_id}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_id}')
        AND (ready_probe_json #>> '{runner,runner_id}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_id}')
        AND (health_probe_json #>> '{runner,runner_generation}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_generation}')
        AND (ready_probe_json #>> '{runner,runner_generation}') IS NOT DISTINCT FROM (runtime_fact_json #>> '{runner,runner_generation}')))
        AND (state NOT IN ('suspended', 'disposed') OR (stop_fact_json IS NOT NULL
        AND (stop_fact_json ->> 'outcome') IS NOT DISTINCT FROM 'confirmed_stopped'
        AND (stop_fact_json -> 'binding') IS NOT DISTINCT FROM binding_json
        AND (runtime_fact_json IS NULL OR (runtime_fact_json ->> 'status') IS NOT DISTINCT FROM 'stopped')
        AND (stop_fact_json #>> '{runner,trust_source}') IS NOT DISTINCT FROM 'authenticated_dev_runner')))
)""",
    """CREATE UNIQUE INDEX uq_workspace_development_environments_open_workspace
       ON cloudhelm.workspace_development_environments (workspace_id) WHERE state <> 'disposed'""",
    """CREATE TABLE cloudhelm.workspace_development_environment_operations (
    operation_id VARCHAR(160) NOT NULL,
    environment_id VARCHAR(160) NOT NULL,
    project_id VARCHAR(160) NOT NULL,
    task_id VARCHAR(160) NOT NULL,
    workspace_id VARCHAR(160) NOT NULL,
    action VARCHAR(16) NOT NULL,
    operation_state VARCHAR(16) DEFAULT 'pending' NOT NULL,
    expected_environment_revision BIGINT NOT NULL,
    accepted_environment_revision BIGINT NOT NULL,
    workspace_revision BIGINT NOT NULL,
    write_generation BIGINT NOT NULL,
    binding_json JSONB NOT NULL,
    binding_digest VARCHAR(71) NOT NULL,
    source_manifest_digest VARCHAR(71) NOT NULL,
    data_revision VARCHAR(96) NOT NULL,
    data_generation BIGINT NOT NULL,
    request_json JSONB NOT NULL,
    command_request_digest VARCHAR(71) NOT NULL,
    request_digest VARCHAR(71) NOT NULL,
    observation_json JSONB,
    observation_digest VARCHAR(71),
    command_id VARCHAR(160) NOT NULL,
    authorization_decision_id VARCHAR(160) NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    closed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_workspace_development_environment_operations PRIMARY KEY (operation_id),
    CONSTRAINT fk_workspace_development_environment_operations_command FOREIGN KEY(command_id) REFERENCES cloudhelm.commands (command_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_workspace_development_environment_operations_command_id UNIQUE (command_id),
    CONSTRAINT fk_workspace_development_environment_operations_authorization FOREIGN KEY(authorization_decision_id) REFERENCES cloudhelm.audit_records (decision_id),
    CONSTRAINT fk_workspace_development_environment_operations_scope FOREIGN KEY(environment_id, project_id, task_id, workspace_id) REFERENCES cloudhelm.workspace_development_environments (environment_id, project_id, task_id, workspace_id),
    CONSTRAINT uq_workspace_development_environment_operation_revision UNIQUE (environment_id, accepted_environment_revision),
    CONSTRAINT ck_workspace_development_environment_operations_op_identity CHECK (operation_id = 'workspace-dev-env-' || action || '-' || command_id),
    CONSTRAINT ck_workspace_development_environment_operations_action CHECK (action IN ('prepare', 'suspend', 'resume', 'reset_data', 'dispose')),
    CONSTRAINT ck_workspace_development_environment_operations_operation_state CHECK (operation_state IN ('pending', 'unknown', 'succeeded', 'failed')),
    CONSTRAINT ck_workspace_development_environment_operations_environment_rev CHECK (
        expected_environment_revision BETWEEN 0 AND 9007199254740990
        AND accepted_environment_revision = expected_environment_revision + 1),
    CONSTRAINT ck_workspace_development_environment_operations_prepare_rev CHECK (
        (action = 'prepare' AND expected_environment_revision = 0)
        OR (action <> 'prepare' AND expected_environment_revision > 0)),
    CONSTRAINT ck_workspace_development_environment_operations_workspace_rev CHECK (workspace_revision BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environment_operations_write_gen CHECK (write_generation BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environment_operations_data_generation CHECK (data_generation BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_workspace_development_environment_operations_binding_digest CHECK (binding_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environment_operations_source_digest CHECK (source_manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environment_operations_request_digests CHECK (
        command_request_digest ~ '^sha256:[0-9a-f]{64}$' AND request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workspace_development_environment_operations_binding CHECK (
        jsonb_typeof(binding_json) = 'object' AND octet_length(binding_json::text) <= 16384
        AND (binding_json ->> 'workspace_id') IS NOT DISTINCT FROM workspace_id
        AND (binding_json ->> 'project_id') IS NOT DISTINCT FROM project_id
        AND (binding_json ->> 'task_id') IS NOT DISTINCT FROM task_id
        AND COALESCE((binding_json ->> 'base_commit') ~ '^([0-9a-f]{40}|[0-9a-f]{64})$', false)
        AND (binding_json ->> 'workspace_revision') IS NOT DISTINCT FROM workspace_revision::text
        AND (binding_json ->> 'write_generation') IS NOT DISTINCT FROM write_generation::text),
    CONSTRAINT ck_workspace_development_environment_operations_request CHECK (
        jsonb_typeof(request_json) = 'object' AND octet_length(request_json::text) <= 32768
        AND (request_json ->> 'operation_id') IS NOT DISTINCT FROM operation_id
        AND (request_json ->> 'action') IS NOT DISTINCT FROM action
        AND (request_json ->> 'environment_id') IS NOT DISTINCT FROM environment_id
        AND (request_json -> 'binding') IS NOT DISTINCT FROM binding_json),
    CONSTRAINT ck_workspace_development_environment_operations_observation CHECK (
        (observation_json IS NULL AND observation_digest IS NULL) OR
        (observation_json IS NOT NULL AND observation_digest IS NOT NULL AND observation_digest ~ '^sha256:[0-9a-f]{64}$'
        AND jsonb_typeof(observation_json) = 'object' AND octet_length(observation_json::text) <= 32768
        AND (observation_json ->> 'operation_id') IS NOT DISTINCT FROM operation_id
        AND (observation_json ->> 'request_digest') IS NOT DISTINCT FROM request_digest
        AND (observation_json ->> 'environment_id') IS NOT DISTINCT FROM environment_id)),
    CONSTRAINT ck_workspace_development_environment_operations_closure_receipt CHECK (
        (operation_state IN ('pending', 'unknown') AND closed_at IS NULL) OR
        (operation_state IN ('succeeded', 'failed') AND closed_at IS NOT NULL AND observation_json IS NOT NULL))
)""",
    """CREATE UNIQUE INDEX uq_workspace_development_environment_operations_open
       ON cloudhelm.workspace_development_environment_operations (environment_id)
       WHERE operation_state IN ('pending', 'unknown')""",
    """CREATE INDEX ix_workspace_development_environment_operations_task_state
       ON cloudhelm.workspace_development_environment_operations (task_id, operation_state)""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("p1_workspace_development_downgrade_not_supported")
