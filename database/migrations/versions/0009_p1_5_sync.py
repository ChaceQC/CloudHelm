"""Durable project dispatch order; never derive a cursor from business IDs."""

from alembic import op

revision = "0009_p1_5_sync"
down_revision = "0008_p1_4_remote"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.sync_streams (
        project_id VARCHAR(160) PRIMARY KEY REFERENCES cloudhelm.projects(project_id),
        stream_id VARCHAR(160) NOT NULL UNIQUE,
        last_cursor BIGINT NOT NULL DEFAULT 0, retained_from BIGINT NOT NULL DEFAULT 0,
        CONSTRAINT ck_sync_streams_cursor_range CHECK
            (0 <= retained_from AND retained_from <= last_cursor AND last_cursor <= 9007199254740991)
    )""")
    op.execute("""CREATE TABLE cloudhelm.sync_dispatch_events (
        project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.sync_streams(project_id),
        cursor BIGINT NOT NULL,
        event_id VARCHAR(160) NOT NULL UNIQUE REFERENCES cloudhelm.event_log(event_id),
        PRIMARY KEY (project_id, cursor),
        CONSTRAINT ck_sync_dispatch_events_cursor_range CHECK
            (cursor > 0 AND cursor <= 9007199254740991)
    )""")
    op.execute("CREATE INDEX ix_outbox_pending ON cloudhelm.outbox (created_at, event_id) WHERE dispatched_at IS NULL")


def downgrade():
    raise RuntimeError("sync_cursor_reconciliation_required")
