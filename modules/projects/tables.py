"""Project identity and ownership; role grants belong to identity."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Table, func,
)

from database.metadata import metadata


projects = Table(
    "projects", metadata,
    Column("project_id", String(160), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("owner_user_id", String(160), ForeignKey("cloudhelm.users.user_id"), nullable=False),
    Column("revision", BigInteger, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("length(name) BETWEEN 1 AND 160", name="project_name_length"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="project_revision_positive"),
)
