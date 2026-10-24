"""Shared host resource pools, registered executors and persistent reservations."""

from alembic import op

revision = "0005_p1_3_resources"
down_revision = "0004_p1_2_development"
branch_labels = None
depends_on = None

# Frozen DDL: future application metadata is never used by this revision.
STATEMENTS = (
    """CREATE TABLE cloudhelm.resource_pools (
    host_resource_pool_id VARCHAR(160) NOT NULL,
    physical_host_id VARCHAR(160) NOT NULL,
    registration_json JSONB NOT NULL,
    lock_revision BIGINT DEFAULT '1' NOT NULL,
    CONSTRAINT pk_resource_pools PRIMARY KEY (host_resource_pool_id),
    CONSTRAINT ck_resource_pools_lock_revision CHECK (lock_revision BETWEEN 1 AND 9007199254740991),
    CONSTRAINT uq_resource_pools_physical_host_id UNIQUE (physical_host_id)
)""",
    """CREATE TABLE cloudhelm.resource_runners (
    executor_instance_id VARCHAR(160) NOT NULL,
    host_resource_pool_id VARCHAR(160) NOT NULL,
    registration_json JSONB NOT NULL,
    CONSTRAINT pk_resource_runners PRIMARY KEY (executor_instance_id),
    CONSTRAINT fk_resource_runners_host_resource_pool_id_resource_pools FOREIGN KEY(host_resource_pool_id) REFERENCES cloudhelm.resource_pools (host_resource_pool_id)
)""",
    """CREATE TABLE cloudhelm.resource_reservations (
    reservation_id VARCHAR(160) NOT NULL,
    host_resource_pool_id VARCHAR(160) NOT NULL,
    executor_instance_id VARCHAR(160) NOT NULL,
    operation_id VARCHAR(160) NOT NULL,
    task_id VARCHAR(160) NOT NULL,
    command_id VARCHAR(160) NOT NULL,
    request_json JSONB NOT NULL,
    allocation_json JSONB NOT NULL,
    receipt_json JSONB,
    receipt_sequence BIGINT DEFAULT '0' NOT NULL,
    CONSTRAINT pk_resource_reservations PRIMARY KEY (reservation_id),
    CONSTRAINT uq_resource_reservation_pool UNIQUE (reservation_id, host_resource_pool_id),
    CONSTRAINT ck_resource_reservations_receipt_sequence CHECK (receipt_sequence BETWEEN 0 AND 9007199254740991),
    CONSTRAINT fk_resource_reservations_host_resource_pool_id_resource_pools FOREIGN KEY(host_resource_pool_id) REFERENCES cloudhelm.resource_pools (host_resource_pool_id),
    CONSTRAINT fk_resource_reservations_executor_instance_id_resource_runners FOREIGN KEY(executor_instance_id) REFERENCES cloudhelm.resource_runners (executor_instance_id),
    CONSTRAINT uq_resource_reservations_operation_id UNIQUE (operation_id),
    CONSTRAINT fk_resource_reservations_task_id_tasks FOREIGN KEY(task_id) REFERENCES cloudhelm.tasks (task_id),
    CONSTRAINT uq_resource_reservations_command_id UNIQUE (command_id),
    CONSTRAINT fk_resource_reservations_command_id_commands FOREIGN KEY(command_id) REFERENCES cloudhelm.commands (command_id) DEFERRABLE INITIALLY DEFERRED
)""",
)


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    raise RuntimeError("resource_ledger_downgrade_requires_explicit_reconciliation")
