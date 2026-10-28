"""Explicit registration of the current business tables, without service startup."""

from importlib import import_module

from sqlalchemy import MetaData

from database.metadata import metadata

TABLE_MODULES = (
    "database.tables", "database.archive_maintenance_tables", "database.commands", "modules.sync.tables", "modules.workflow.tables",
    "modules.identity.tables", "modules.projects.tables", "modules.collaboration.tables",
    "modules.projects.source_tables", "modules.projects.source_import_tables", "modules.workspaces.tables",
    "modules.workspaces.development_tables", "modules.delivery.tables", "modules.execution.tables",
    "modules.delivery.deployment_tables",
    "modules.delivery.remote_tables",
    "modules.agent_runtime.tables",
)


def load_business_metadata() -> MetaData:
    """Load declarations only; no configuration, connections, DDL or migrations."""
    for module in TABLE_MODULES:
        import_module(module)
    return metadata
