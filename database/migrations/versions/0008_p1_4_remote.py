"""Maintenance enrollment and append-only remote time/permit/result projections."""

from alembic import op

revision = "0008_p1_4_remote"
down_revision = "0007_p1_4_delivery"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.delivery_remote_credentials (
        credential_id VARCHAR(160) PRIMARY KEY,
        project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.projects(project_id),
        target_id VARCHAR(160) NOT NULL, installation_id VARCHAR(160) NOT NULL,
        token_digest BYTEA NOT NULL UNIQUE, expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        revoked BOOLEAN NOT NULL DEFAULT false, lock_revision INTEGER NOT NULL DEFAULT 0
    )""")
    for name in ("delivery_remote_samples", "delivery_remote_grants", "delivery_remote_results"):
        op.execute(f"""CREATE TABLE cloudhelm.{name} (
            id VARCHAR(160) PRIMARY KEY,
            credential_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.delivery_remote_credentials(credential_id),
            operation_id VARCHAR(160), step_id VARCHAR(160), digest VARCHAR(71) NOT NULL,
            value_json JSONB NOT NULL,
            CONSTRAINT ck_{name}_bounded_payload CHECK (octet_length(value_json::text) <= 65536)
        )""")


def downgrade():
    raise RuntimeError("remote_ledger_reconciliation_required")
