"""Append remote closeout receipts and authorized human closeout facts."""

from alembic import op

revision = "0010_p1_archive_closeout"
down_revision = "0009_p1_5_sync"
branch_labels = depends_on = None


def upgrade():
    # Fixed declarations are independent of future metadata changes.
    op.execute("""CREATE TABLE cloudhelm.deployment_closeouts (
        operation_id VARCHAR(160) PRIMARY KEY,
        project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.projects(project_id),
        digest VARCHAR(71) NOT NULL,
        value_json JSONB NOT NULL,
        command_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.commands(command_id) DEFERRABLE INITIALLY DEFERRED,
        authorization_decision_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.audit_records(decision_id),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT ck_deployment_closeouts_digest CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_deployment_closeouts_bounded_payload CHECK (jsonb_typeof(value_json) = 'object'
            AND octet_length(value_json::text) <= 131072)
    )""")
    op.execute("""CREATE TABLE cloudhelm.delivery_remote_closeouts (
        id VARCHAR(160) PRIMARY KEY,
        credential_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.delivery_remote_credentials(credential_id),
        operation_id VARCHAR(160), step_id VARCHAR(160), digest VARCHAR(71) NOT NULL,
        value_json JSONB NOT NULL,
        CONSTRAINT ck_delivery_remote_closeouts_bounded_payload CHECK (octet_length(value_json::text) <= 65536)
    )""")


def downgrade():
    raise RuntimeError("archive_closeout_downgrade_requires_reconciliation_of_closed_operations")
