"""Persist explicit workspace write ownership and versioned handoff snapshots."""

from alembic import op

revision = "0015_p2_handoffs"
down_revision = "0014_p2_verification"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.workspace_handoffs (
        handoff_id VARCHAR(160) PRIMARY KEY,
        workspace_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.workspaces(workspace_id),
        task_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.tasks(task_id),
        state VARCHAR(24) NOT NULL,
        record_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_workspace_handoffs_state
            CHECK (state IN ('handoff_pending', 'human_owned', 'return_pending', 'agent_owned')),
        CONSTRAINT ck_workspace_handoffs_record_bounded
            CHECK (jsonb_typeof(record_json) = 'object' AND octet_length(record_json::text) <= 16777216),
        CONSTRAINT ck_workspace_handoffs_record_identity
            CHECK (record_json ->> 'state' = state AND record_json ->> 'handoff_id' = handoff_id
                AND record_json ->> 'workspace_id' = workspace_id AND record_json ->> 'task_id' = task_id)
    )""")
    op.execute("CREATE INDEX ix_workspace_handoffs_task_id ON cloudhelm.workspace_handoffs(task_id)")
    op.execute("CREATE UNIQUE INDEX uq_workspace_handoffs_owner ON cloudhelm.workspace_handoffs(workspace_id) "
               "WHERE state <> 'agent_owned'")


def downgrade():
    raise RuntimeError("workspace_handoff_downgrade_requires_reconciliation")
