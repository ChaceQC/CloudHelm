"""Immutable event facts and their durable, not-yet-dispatched outbox references."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Table, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import BUSINESS_SCHEMA, metadata

event_log = Table(
    "event_log", metadata,
    Column("event_id", String(160), primary_key=True),
    Column("command_id", String(160), ForeignKey(
        f"{BUSINESS_SCHEMA}.commands.command_id", deferrable=True, initially="DEFERRED"
    ), nullable=False),
    Column("project_id", String(160), nullable=False),
    Column("aggregate_kind", String(160), nullable=False),
    Column("aggregate_id", String(160), nullable=False),
    Column("aggregate_version", BigInteger, nullable=False),
    Column("event_type", String(160), nullable=False),
    Column("schema_version", String(160), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "aggregate_version >= 0 AND aggregate_version <= 9007199254740991",
        name="aggregate_version",
    ),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
)

outbox = Table(
    "outbox", metadata,
    Column("event_id", String(160),
           ForeignKey(f"{BUSINESS_SCHEMA}.event_log.event_id"), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("dispatched_at", DateTime(timezone=True)),
)

streams = Table(
    "sync_streams", metadata,
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), primary_key=True),
    Column("stream_id", String(160), nullable=False, unique=True),
    Column("last_cursor", BigInteger, nullable=False, server_default="0"),
    Column("retained_from", BigInteger, nullable=False, server_default="0"),
    CheckConstraint("0 <= retained_from AND retained_from <= last_cursor "
                    "AND last_cursor <= 9007199254740991", name="cursor_range"),
)

dispatch_events = Table(
    "sync_dispatch_events", metadata,
    Column("project_id", String(160), ForeignKey("cloudhelm.sync_streams.project_id"), primary_key=True),
    Column("cursor", BigInteger, primary_key=True),
    Column("event_id", String(160), ForeignKey("cloudhelm.event_log.event_id"), nullable=False, unique=True),
    CheckConstraint("cursor > 0 AND cursor <= 9007199254740991", name="cursor_range"),
)
