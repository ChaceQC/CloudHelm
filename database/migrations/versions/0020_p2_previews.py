"""Persist controlled previews, one-time access and optional human-test rounds."""

from alembic import op

from modules.integration.human_test_tables import human_test_sessions
from modules.workspaces.preview_access_tables import preview_authorizations, preview_environments
from modules.workspaces.preview_environment_tables import preview_environment_intents

revision = "0020_p2_previews"
down_revision = "0019_p2_history_limit"
branch_labels = depends_on = None


def upgrade():
    op.execute("GRANT UPDATE (human_conclusion_key) ON cloudhelm.task_inputs TO cloudhelm_api")
    op.execute("ALTER TABLE cloudhelm.role_bindings DROP CONSTRAINT ck_role_bindings_binding_supported_role")
    op.execute("ALTER TABLE cloudhelm.role_bindings ADD CONSTRAINT ck_role_bindings_binding_supported_role "
               "CHECK (role IN ('developer','reviewer','tester','deployment_approver'))")
    for table in (human_test_sessions, preview_environments, preview_authorizations, preview_environment_intents):
        table.create(op.get_bind())


def downgrade():
    raise RuntimeError("preview_downgrade_requires_access_and_execution_reconciliation")
