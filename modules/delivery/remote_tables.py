"""Hub projections of executor facts and maintenance-owned channel enrollment."""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Table
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

remote_credentials = Table("delivery_remote_credentials", metadata,
    Column("credential_id", String(160), primary_key=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("target_id", String(160), nullable=False),
    Column("installation_id", String(160), nullable=False),
    Column("token_digest", LargeBinary, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked", Boolean, nullable=False, server_default="false"),
    Column("lock_revision", Integer, nullable=False, server_default="0"),
)


def _projection(name):
    return Table(name, metadata,
        Column("id", String(160), primary_key=True),
        Column("credential_id", String(160), ForeignKey("cloudhelm.delivery_remote_credentials.credential_id"), nullable=False),
        Column("operation_id", String(160)),
        Column("step_id", String(160)),
        Column("digest", String(71), nullable=False),
        Column("value_json", JSONB, nullable=False),
        CheckConstraint("octet_length(value_json::text) <= 65536", name="bounded_payload"),
    )


remote_samples = _projection("delivery_remote_samples")
remote_grants = _projection("delivery_remote_grants")
remote_results = _projection("delivery_remote_results")
remote_closeouts = _projection("delivery_remote_closeouts")
