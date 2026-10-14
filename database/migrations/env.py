"""Alembic runs only on the connection supplied by controlled maintenance."""

from alembic import context
from sqlalchemy.engine import Connection

from database.metadata import BUSINESS_SCHEMA


def run_migrations() -> None:
    connection = context.config.attributes.get("connection")
    if context.is_offline_mode() or not isinstance(connection, Connection):
        raise RuntimeError("controlled_migration_connection_required")
    context.configure(
        connection=connection, version_table_schema=BUSINESS_SCHEMA,
        transaction_per_migration=False, transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
