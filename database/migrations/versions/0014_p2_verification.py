"""Index exact verification dependencies without rewriting historical reports."""

from alembic import op

revision = "0014_p2_verification"
down_revision = "0013_p2_usage_waits"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.verification_dependencies (
        report_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.event_log(event_id),
        producer_key VARCHAR(71) NOT NULL,
        task_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.tasks(task_id),
        applicability VARCHAR(16) NOT NULL,
        CONSTRAINT pk_verification_dependencies PRIMARY KEY (report_id, producer_key),
        CONSTRAINT ck_verification_dependencies_verification_applicability
            CHECK (applicability IN ('valid', 'needs_review'))
    )""")
    op.execute("CREATE INDEX ix_verification_dependencies_producer_key ON cloudhelm.verification_dependencies(producer_key)")
    op.execute("CREATE INDEX ix_verification_dependencies_task_id ON cloudhelm.verification_dependencies(task_id)")


def downgrade():
    raise RuntimeError("verification_downgrade_requires_reconciliation")
