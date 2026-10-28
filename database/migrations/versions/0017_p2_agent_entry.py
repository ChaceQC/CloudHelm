"""Allow the API to register bounded Runs without worker execution privileges."""

from alembic import op

revision = "0017_p2_agent_entry"
down_revision = "0016_p2_merge_queue"
branch_labels = depends_on = None


def upgrade():
    op.execute("GRANT INSERT ON cloudhelm.agent_sessions, cloudhelm.agent_runs TO cloudhelm_api")
    op.execute("GRANT UPDATE (state) ON cloudhelm.agent_sessions TO cloudhelm_api")


def downgrade():
    raise RuntimeError("agent_entry_downgrade_requires_reconciliation")
