"""Durable preparation and cleanup intents share the existing DBOS handoff."""

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

preview_environment_intents = Table(
    "preview_environment_intents", metadata,
    Column("operation_id", String(160), primary_key=True),
    Column("environment_id", String(160), ForeignKey("cloudhelm.preview_environments.environment_id"), nullable=False),
    Column("command_id", String(160), ForeignKey("cloudhelm.commands.command_id", deferrable=True,
                                               initially="DEFERRED"), nullable=False),
    Column("action", String(16), nullable=False),
    Column("request_json", JSONB, nullable=False),
    Column("reason", String(160)),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
