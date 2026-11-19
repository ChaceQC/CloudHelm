"""Persist the declared Run prerequisites of a WorkItem."""

from alembic import op

revision = "0021_p2_work_item_run"
down_revision = "0020_p2_previews"
branch_labels = depends_on = None


def upgrade():
    op.execute("""ALTER TABLE cloudhelm.work_items
        ADD COLUMN run_requirements_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD CONSTRAINT ck_work_items_run_requirements_bounded CHECK (
            jsonb_typeof(run_requirements_json) = 'object' AND octet_length(run_requirements_json::text) <= 32768
        )""")


def downgrade():
    raise RuntimeError("work_item_run_requirements_downgrade_requires_reconciliation")
