"""Immutable build inputs and engineering handoff; fresh isolated installations only."""

from alembic import op

revision = "0003_p1_2_builds"
down_revision = "0002_p1_2"
branch_labels = None
depends_on = None

STATEMENTS = (
    """ALTER TABLE cloudhelm.workspace_candidates ADD CONSTRAINT uq_candidate_task_owner
       UNIQUE (candidate_id, project_id, task_id)""",
    """ALTER TABLE cloudhelm.workspaces DROP CONSTRAINT ck_workspaces_files_receipt_complete""",
    """ALTER TABLE cloudhelm.workspaces ADD CONSTRAINT ck_workspaces_files_receipt_complete CHECK (
    (files_json IS NULL AND files_digest IS NULL AND materialization_operation_id IS NULL AND storage_id IS NULL) OR
    (files_json IS NOT NULL AND files_digest IS NOT NULL AND materialization_operation_id IS NOT NULL
    AND storage_id IS NOT NULL AND files_digest ~ '^sha256:[0-9a-f]{64}$'
    AND jsonb_typeof(files_json) = 'object' AND octet_length(files_json::text) <= 32768
    AND (files_json #>> '{binding,workspace_id}') IS NOT DISTINCT FROM workspace_id
    AND (files_json #>> '{binding,project_id}') IS NOT DISTINCT FROM project_id
    AND (files_json #>> '{binding,task_id}') IS NOT DISTINCT FROM task_id
    AND (files_json #>> '{binding,work_item_id}') IS NOT DISTINCT FROM work_item_id
    AND (files_json #>> '{binding,owner_user_id}') IS NOT DISTINCT FROM owner_user_id
    AND (files_json #>> '{binding,source_id}') IS NOT DISTINCT FROM source_id
    AND (files_json #>> '{binding,source_revision}') IS NOT DISTINCT FROM source_revision::text
    AND (files_json #>> '{binding,base_commit}') IS NOT DISTINCT FROM base_commit
    AND CASE WHEN jsonb_typeof(files_json #> '{binding,workspace_revision}') = 'number'
    AND (files_json #>> '{binding,workspace_revision}') ~ '^(0|[1-9][0-9]{0,15})$'
    THEN (files_json #>> '{binding,workspace_revision}')::numeric BETWEEN 0 AND workspace_revision ELSE false END
    AND CASE WHEN jsonb_typeof(files_json #> '{binding,write_generation}') = 'number'
    AND (files_json #>> '{binding,write_generation}') ~ '^(0|[1-9][0-9]{0,15})$'
    THEN (files_json #>> '{binding,write_generation}')::numeric BETWEEN 0 AND write_generation ELSE false END
    AND (files_json ->> 'operation_id') IS NOT DISTINCT FROM materialization_operation_id
    AND (files_json ->> 'storage_id') IS NOT DISTINCT FROM storage_id))""",
    """ALTER TABLE cloudhelm.workflow_bindings DROP CONSTRAINT ck_workflow_bindings_p1_business_kind""",
    """ALTER TABLE cloudhelm.workflow_bindings ADD CONSTRAINT ck_workflow_bindings_p1_business_kind
       CHECK (business_kind IN ('task', 'project', 'workspace', 'build'))""",
    """CREATE TABLE cloudhelm.build_runs (
    build_run_id VARCHAR(160) NOT NULL,
    operation_id VARCHAR(160) NOT NULL,
    command_id VARCHAR(160) NOT NULL,
    project_id VARCHAR(160) NOT NULL,
    task_id VARCHAR(160) NOT NULL,
    candidate_id VARCHAR(160) NOT NULL,
    expected_task_version BIGINT NOT NULL,
    accepted_task_version BIGINT NOT NULL,
    control_revision BIGINT NOT NULL,
    input_validity_revision BIGINT NOT NULL,
    input_set_key VARCHAR(71) NOT NULL,
    request_json JSONB NOT NULL,
    command_request_digest VARCHAR(71) NOT NULL,
    request_digest VARCHAR(71) NOT NULL,
    fixed_inputs_json JSONB NOT NULL,
    build_input_digest VARCHAR(71) NOT NULL,
    authorization_decision_id VARCHAR(160) NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_build_runs PRIMARY KEY (build_run_id),
    CONSTRAINT uq_build_runs_operation_id UNIQUE (operation_id),
    CONSTRAINT uq_build_runs_command_id UNIQUE (command_id),
    CONSTRAINT fk_build_runs_command FOREIGN KEY(command_id) REFERENCES cloudhelm.commands (command_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_build_runs_input_set FOREIGN KEY(input_set_key) REFERENCES cloudhelm.task_reference_records (reference_key),
    CONSTRAINT fk_build_runs_authorization FOREIGN KEY(authorization_decision_id) REFERENCES cloudhelm.audit_records (decision_id),
    CONSTRAINT fk_build_runs_task FOREIGN KEY(project_id, task_id) REFERENCES cloudhelm.tasks (project_id, task_id),
    CONSTRAINT fk_build_runs_candidate_owner FOREIGN KEY(candidate_id, project_id, task_id) REFERENCES cloudhelm.workspace_candidates (candidate_id, project_id, task_id),
    CONSTRAINT fk_build_runs_task_input_revision FOREIGN KEY(task_id, input_validity_revision) REFERENCES cloudhelm.task_inputs (task_id, input_validity_revision),
    CONSTRAINT ck_build_runs_operation_identity CHECK (build_run_id = 'build-' || command_id AND operation_id = 'build-operation-' || command_id),
    CONSTRAINT ck_build_runs_task_version CHECK (expected_task_version BETWEEN 1 AND 9007199254740990 AND accepted_task_version = expected_task_version + 1),
    CONSTRAINT ck_build_runs_task_revisions CHECK (control_revision BETWEEN 0 AND 9007199254740991 AND input_validity_revision BETWEEN 1 AND 9007199254740991),
    CONSTRAINT ck_build_runs_digests CHECK (command_request_digest ~ '^sha256:[0-9a-f]{64}$' AND request_digest ~ '^sha256:[0-9a-f]{64}$' AND build_input_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_build_runs_request_binding CHECK (jsonb_typeof(request_json) = 'object' AND octet_length(request_json::text) <= 65536 AND (request_json ->> 'candidate_id') IS NOT DISTINCT FROM candidate_id AND (request_json ->> 'expected_version') IS NOT DISTINCT FROM expected_task_version::text AND (request_json ->> 'expected_control_revision') IS NOT DISTINCT FROM control_revision::text AND (request_json ->> 'expected_input_validity_revision') IS NOT DISTINCT FROM input_validity_revision::text),
    CONSTRAINT ck_build_runs_fixed_inputs_binding CHECK (jsonb_typeof(fixed_inputs_json) = 'object' AND octet_length(fixed_inputs_json::text) <= 131072 AND (fixed_inputs_json #>> '{candidate,candidate_id}') IS NOT DISTINCT FROM candidate_id AND (fixed_inputs_json #>> '{candidate,binding,project_id}') IS NOT DISTINCT FROM project_id AND (fixed_inputs_json #>> '{candidate,binding,task_id}') IS NOT DISTINCT FROM task_id AND (fixed_inputs_json -> 'definition') IS NOT DISTINCT FROM (request_json -> 'definition') AND (fixed_inputs_json -> 'source_input_set_ref') IS NOT DISTINCT FROM (request_json -> 'input_set_ref'))
)""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("p1_build_downgrade_not_supported")
