"""Allow admitted worker Gateway commands to register development environment intents."""

from alembic import op

revision = "0018_p2_agent_environment"
down_revision = "0017_p2_agent_entry"
branch_labels = depends_on = None


def upgrade():
    op.execute("GRANT INSERT ON cloudhelm.workspace_development_environments, "
               "cloudhelm.workspace_development_environment_operations TO cloudhelm_worker")
    op.execute("GRANT UPDATE (environment_revision) ON cloudhelm.workspace_development_environments TO cloudhelm_worker")


def downgrade():
    raise RuntimeError("agent_environment_downgrade_requires_reconciliation")
