"""Reverse references and current applicability; report facts remain immutable events."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, String, Table

from database.metadata import metadata

verification_dependencies = Table(
    "verification_dependencies", metadata,
    Column("report_id", String(160), ForeignKey("cloudhelm.event_log.event_id"), primary_key=True),
    Column("producer_key", String(71), primary_key=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("applicability", String(16), nullable=False),
    CheckConstraint("applicability IN ('valid', 'needs_review')", name="verification_applicability"),
)
Index("ix_verification_dependencies_producer_key", verification_dependencies.c.producer_key)
Index("ix_verification_dependencies_task_id", verification_dependencies.c.task_id)
