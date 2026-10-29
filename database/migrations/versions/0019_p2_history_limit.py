"""Fit measured engineering tool history within a fixed 256 KiB archive budget."""

from alembic import op

revision = "0019_p2_history_limit"
down_revision = "0018_p2_agent_environment"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE cloudhelm.agent_histories DROP CONSTRAINT ck_agent_histories_value_bounded")
    op.execute("ALTER TABLE cloudhelm.agent_histories ADD CONSTRAINT ck_agent_histories_value_bounded "
               "CHECK (octet_length(value_json::text) <= 262144)")


def downgrade():
    raise RuntimeError("history_budget_reduction_requires_reconciliation")
