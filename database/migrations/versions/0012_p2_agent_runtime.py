"""Add the bounded Agent Runtime ledger after the archive maintenance baseline."""

from alembic import op

revision = "0012_p2_agent_runtime"
down_revision = "0011_p1_archive_maintenance"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.agent_sessions (
        session_id VARCHAR(160) NOT NULL,
        task_id VARCHAR(160) NOT NULL,
        source_command_id VARCHAR(160) NOT NULL,
        version BIGINT NOT NULL DEFAULT 0,
        state VARCHAR(16) NOT NULL DEFAULT 'idle',
        epoch_id VARCHAR(160) NOT NULL,
        history_key VARCHAR(71),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT pk_agent_sessions PRIMARY KEY (session_id),
        CONSTRAINT fk_agent_sessions_task_id_tasks FOREIGN KEY (task_id) REFERENCES cloudhelm.tasks(task_id),
        CONSTRAINT fk_agent_sessions_source_command_id_commands FOREIGN KEY (source_command_id)
            REFERENCES cloudhelm.commands(command_id) DEFERRABLE INITIALLY DEFERRED,
        CONSTRAINT ck_agent_sessions_version CHECK (version BETWEEN 0 AND 9007199254740991),
        CONSTRAINT ck_agent_sessions_state CHECK (state IN ('idle', 'queued', 'running', 'paused', 'failed', 'completed'))
    )""")
    op.execute("""CREATE TABLE cloudhelm.agent_runs (
        run_id VARCHAR(160) NOT NULL,
        session_id VARCHAR(160) NOT NULL,
        source_command_id VARCHAR(160) NOT NULL,
        workflow_id VARCHAR(160) NOT NULL,
        request_digest VARCHAR(71) NOT NULL,
        start_json JSONB NOT NULL,
        state VARCHAR(16) NOT NULL DEFAULT 'queued',
        request_count INTEGER NOT NULL DEFAULT 0,
        reserved_cost NUMERIC(28,12) NOT NULL DEFAULT 0,
        started_at TIMESTAMP WITH TIME ZONE,
        deadline_at TIMESTAMP WITH TIME ZONE,
        result_json JSONB,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT pk_agent_runs PRIMARY KEY (run_id),
        CONSTRAINT fk_agent_runs_session_id_agent_sessions FOREIGN KEY (session_id)
            REFERENCES cloudhelm.agent_sessions(session_id),
        CONSTRAINT fk_agent_runs_source_command_id_commands FOREIGN KEY (source_command_id)
            REFERENCES cloudhelm.commands(command_id) DEFERRABLE INITIALLY DEFERRED,
        CONSTRAINT uq_agent_runs_workflow_id UNIQUE (workflow_id),
        CONSTRAINT ck_agent_runs_state CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')),
        CONSTRAINT ck_agent_runs_start_bounded CHECK (octet_length(start_json::text) <= 65536),
        CONSTRAINT ck_agent_runs_result_bounded CHECK (octet_length(result_json::text) <= 16384),
        CONSTRAINT ck_agent_runs_admission_totals CHECK (request_count >= 0 AND reserved_cost >= 0)
    )""")
    op.execute("""CREATE UNIQUE INDEX uq_agent_runs_active_session ON cloudhelm.agent_runs (session_id)
        WHERE state IN ('queued', 'running')""")
    op.execute("""CREATE TABLE cloudhelm.agent_model_requests (
        request_record_id VARCHAR(160) NOT NULL,
        run_id VARCHAR(160) NOT NULL,
        request_sequence INTEGER NOT NULL,
        body_digest VARCHAR(71) NOT NULL,
        body_bytes INTEGER NOT NULL,
        reserved_cost NUMERIC(28,12) NOT NULL,
        state VARCHAR(16) NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT pk_agent_model_requests PRIMARY KEY (request_record_id),
        CONSTRAINT fk_agent_model_requests_run_id_agent_runs FOREIGN KEY (run_id) REFERENCES cloudhelm.agent_runs(run_id),
        CONSTRAINT uq_agent_model_requests_run_sequence UNIQUE (run_id, request_sequence),
        CONSTRAINT ck_agent_model_requests_state CHECK (state = 'unknown'),
        CONSTRAINT ck_agent_model_requests_admission_values CHECK
            (request_sequence >= 0 AND body_bytes >= 0 AND reserved_cost >= 0)
    )""")
    op.execute("""CREATE TABLE cloudhelm.agent_histories (
        history_key VARCHAR(71) NOT NULL,
        session_id VARCHAR(160) NOT NULL,
        value_json JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT pk_agent_histories PRIMARY KEY (history_key, session_id),
        CONSTRAINT fk_agent_histories_session_id_agent_sessions FOREIGN KEY (session_id)
            REFERENCES cloudhelm.agent_sessions(session_id),
        CONSTRAINT ck_agent_histories_value_bounded CHECK (octet_length(value_json::text) <= 131072)
    )""")
    op.execute("ALTER TABLE cloudhelm.workflow_bindings DROP CONSTRAINT ck_workflow_bindings_p1_business_kind")
    op.execute("""ALTER TABLE cloudhelm.workflow_bindings ADD CONSTRAINT ck_workflow_bindings_p1_business_kind
        CHECK (business_kind IN ('task', 'project', 'workspace', 'build', 'deployment', 'agent_run'))""")


def downgrade():
    raise RuntimeError("agent_runtime_downgrade_requires_reconciliation")
