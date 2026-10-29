"""Persistent Agent sessions, bounded runs, request reservations and histories."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Table, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


agent_sessions = Table(
    "agent_sessions", metadata,
    Column("session_id", String(160), primary_key=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("source_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", deferrable=True, initially="DEFERRED",
    ), nullable=False),
    Column("version", BigInteger, nullable=False, server_default="0"),
    Column("state", String(16), nullable=False, server_default="idle"),
    Column("epoch_id", String(160), nullable=False),
    Column("history_key", String(71)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("version BETWEEN 0 AND 9007199254740991", name="version"),
    CheckConstraint("state IN ('idle', 'queued', 'running', 'paused', 'failed', 'completed')", name="state"),
)

agent_runs = Table(
    "agent_runs", metadata,
    Column("run_id", String(160), primary_key=True),
    Column("session_id", String(160), ForeignKey("cloudhelm.agent_sessions.session_id"), nullable=False),
    Column("source_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", deferrable=True, initially="DEFERRED",
    ), nullable=False),
    Column("workflow_id", String(160), nullable=False, unique=True),
    Column("request_digest", String(71), nullable=False),
    Column("start_json", JSONB, nullable=False),
    Column("state", String(16), nullable=False, server_default="queued"),
    Column("request_count", Integer, nullable=False, server_default="0"),
    Column("reserved_cost", Numeric(28, 12), nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True)),
    Column("deadline_at", DateTime(timezone=True)),
    Column("result_json", JSONB(none_as_null=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')", name="state"),
    CheckConstraint("octet_length(start_json::text) <= 65536", name="start_bounded"),
    CheckConstraint("octet_length(result_json::text) <= 16384", name="result_bounded"),
    CheckConstraint("request_count >= 0 AND reserved_cost >= 0", name="admission_totals"),
)
Index(
    "uq_agent_runs_active_session", agent_runs.c.session_id, unique=True,
    postgresql_where=text("state IN ('queued', 'running')"),
)

agent_model_requests = Table(
    "agent_model_requests", metadata,
    Column("request_record_id", String(160), primary_key=True),
    Column("run_id", String(160), ForeignKey("cloudhelm.agent_runs.run_id"), nullable=False),
    Column("request_sequence", Integer, nullable=False),
    Column("body_digest", String(71), nullable=False),
    Column("body_bytes", Integer, nullable=False),
    Column("reserved_cost", Numeric(28, 12), nullable=False),
    Column("state", String(16), nullable=False, server_default="unknown"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("run_id", "request_sequence", name="uq_agent_model_requests_run_sequence"),
    CheckConstraint("state = 'unknown'", name="state"),
    CheckConstraint("request_sequence >= 0 AND body_bytes >= 0 AND reserved_cost >= 0", name="admission_values"),
)

agent_histories = Table(
    "agent_histories", metadata,
    Column("history_key", String(71), primary_key=True),
    Column("session_id", String(160), ForeignKey("cloudhelm.agent_sessions.session_id"), primary_key=True),
    Column("value_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("octet_length(value_json::text) <= 262144", name="value_bounded"),
)
