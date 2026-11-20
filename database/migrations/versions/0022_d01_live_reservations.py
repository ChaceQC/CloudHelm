"""Index reservations that still count toward host pool capacity."""

from alembic import op

revision = "0022_d01_live_reservations"
down_revision = "0021_p2_work_item_run"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE INDEX ix_resource_reservations_live_pool
        ON cloudhelm.resource_reservations (host_resource_pool_id)
        WHERE (allocation_json ->> 'state') IS DISTINCT FROM 'released'""")


def downgrade():
    raise RuntimeError("live_reservations_index_downgrade_not_supported")
