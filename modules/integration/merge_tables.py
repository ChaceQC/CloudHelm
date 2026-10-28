"""One durable FIFO; immutable attempts and reviews live in the event log."""

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Identity, Index, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

merge_queue = Table(
    "merge_queue", metadata,
    Column("entry_id", String(160), primary_key=True),
    Column("position", BigInteger, Identity(), nullable=False, unique=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("state", String(24), nullable=False),
    Column("record_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("state IN ('queued','preparing','awaiting_evidence','applying','merged','conflict','withdrawn')",
                    name="merge_queue_state"),
    CheckConstraint("jsonb_typeof(record_json) = 'object' AND octet_length(record_json::text) <= 65536",
                    name="merge_queue_bounded"),
)
Index("ix_merge_queue_project_position", merge_queue.c.project_id, merge_queue.c.position)
