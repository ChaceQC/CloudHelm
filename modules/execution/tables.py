"""Authoritative Hub resource ledgers; executors own their separate physical facts."""

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata

resource_pools = Table(
    "resource_pools", metadata,
    Column("host_resource_pool_id", String(160), primary_key=True),
    Column("physical_host_id", String(160), nullable=False, unique=True),
    Column("registration_json", JSONB, nullable=False),
    Column("lock_revision", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("lock_revision BETWEEN 1 AND 9007199254740991", name="lock_revision"),
)
resource_runners = Table(
    "resource_runners", metadata,
    Column("executor_instance_id", String(160), primary_key=True),
    Column("host_resource_pool_id", String(160), ForeignKey("cloudhelm.resource_pools.host_resource_pool_id"), nullable=False),
    Column("registration_json", JSONB, nullable=False),
)
resource_reservations = Table(
    "resource_reservations", metadata,
    Column("reservation_id", String(160), primary_key=True),
    Column("host_resource_pool_id", String(160), ForeignKey("cloudhelm.resource_pools.host_resource_pool_id"), nullable=False),
    Column("executor_instance_id", String(160), ForeignKey("cloudhelm.resource_runners.executor_instance_id"), nullable=False),
    Column("operation_id", String(160), nullable=False, unique=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("command_id", String(160), ForeignKey("cloudhelm.commands.command_id", deferrable=True, initially="DEFERRED"), nullable=False, unique=True),
    Column("request_json", JSONB, nullable=False),
    Column("allocation_json", JSONB, nullable=False),
    Column("receipt_json", JSONB(none_as_null=True)),
    Column("receipt_sequence", BigInteger, nullable=False, server_default="0"),
    UniqueConstraint("reservation_id", "host_resource_pool_id", name="uq_resource_reservation_pool"),
    CheckConstraint("receipt_sequence BETWEEN 0 AND 9007199254740991", name="receipt_sequence"),
)

resource_adjustments = Table(
    "resource_adjustments", metadata,
    Column("resource_adjustment_id", String(160), primary_key=True),
    Column("reservation_id", String(160), ForeignKey("cloudhelm.resource_reservations.reservation_id"), nullable=False),
    Column("request_digest", String(71), nullable=False),
    Column("request_json", JSONB, nullable=False),
    Column("result_json", JSONB, nullable=False),
)
