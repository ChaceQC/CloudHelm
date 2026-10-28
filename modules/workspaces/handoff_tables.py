"""Workspace write ownership; immutable snapshots remain in the candidate store."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

workspace_handoffs = Table(
    "workspace_handoffs", metadata,
    Column("handoff_id", String(160), primary_key=True),
    Column("workspace_id", String(160), ForeignKey("cloudhelm.workspaces.workspace_id"), nullable=False),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("state", String(24), nullable=False),
    Column("record_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("state IN ('handoff_pending', 'human_owned', 'return_pending', 'agent_owned')", name="state"),
    CheckConstraint("jsonb_typeof(record_json) = 'object' AND octet_length(record_json::text) <= 16777216",
                    name="record_bounded"),
    CheckConstraint("record_json ->> 'state' = state AND record_json ->> 'handoff_id' = handoff_id "
                    "AND record_json ->> 'workspace_id' = workspace_id AND record_json ->> 'task_id' = task_id",
                    name="record_identity"),
)
Index("ix_workspace_handoffs_task_id", workspace_handoffs.c.task_id)
Index("uq_workspace_handoffs_owner", workspace_handoffs.c.workspace_id, unique=True,
      postgresql_where=text("state <> 'agent_owned'"))
