"""Human-test round state; conclusions are registered as existing Task facts."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKeyConstraint, Index, String, Table,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

human_test_sessions = Table(
    "human_test_sessions", metadata,
    Column("session_id", String(160), primary_key=True),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("round_id", String(160), nullable=False),
    Column("revision", BigInteger, nullable=False),
    Column("state", String(24), nullable=False),
    Column("record_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["project_id", "task_id"], ["cloudhelm.tasks.project_id", "cloudhelm.tasks.task_id"]),
    UniqueConstraint("task_id", "round_id", name="uq_human_test_session_task_round"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="revision"),
    CheckConstraint("state IN ('preparing','awaiting_human','testing','completed','expired','cancelled')",
                    name="state"),
    CheckConstraint("jsonb_typeof(record_json) = 'object' AND octet_length(record_json::text) <= 131072",
                    name="record_bounded"),
    CheckConstraint(
        "(record_json ->> 'session_id') IS NOT DISTINCT FROM session_id "
        "AND (record_json ->> 'project_id') IS NOT DISTINCT FROM project_id "
        "AND (record_json ->> 'task_id') IS NOT DISTINCT FROM task_id "
        "AND (record_json ->> 'round_id') IS NOT DISTINCT FROM round_id "
        "AND (record_json ->> 'revision') IS NOT DISTINCT FROM revision::text "
        "AND (record_json ->> 'state') IS NOT DISTINCT FROM state", name="record_identity",
    ),
)
Index("ix_human_test_sessions_task_id", human_test_sessions.c.task_id)
