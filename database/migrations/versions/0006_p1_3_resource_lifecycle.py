"""Durable independent adjustment identities; stopped disk remains in its allocation."""

from alembic import op

revision = "0006_p1_3_resource_lifecycle"
down_revision = "0005_p1_3_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.resource_adjustments (
        resource_adjustment_id VARCHAR(160) NOT NULL,
        reservation_id VARCHAR(160) NOT NULL,
        request_digest VARCHAR(71) NOT NULL,
        request_json JSONB NOT NULL,
        result_json JSONB NOT NULL,
        CONSTRAINT pk_resource_adjustments PRIMARY KEY (resource_adjustment_id),
        CONSTRAINT fk_resource_adjustments_reservation_id_resource_reservations
            FOREIGN KEY (reservation_id) REFERENCES cloudhelm.resource_reservations (reservation_id)
    )""")


def downgrade():
    raise RuntimeError("resource_lifecycle_downgrade_requires_explicit_reconciliation")
