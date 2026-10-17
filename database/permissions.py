"""Fixed Hub role grants; no runtime role owns schema or mutable audit history."""

from sqlalchemy.engine import Connection

from database.readiness import ROLE_NAMES, require_maintenance_role

DBOS_RUNTIME_ROLE = "cloudhelm_dbos_runtime"
IMMUTABLE_TABLES = (
    "commands", "event_log", "workflow_bindings", "audit_records", "task_declarations",
    "task_inputs", "task_completion_reports", "task_reference_records", "task_evidence_links",
    "task_operation_links", "task_operation_observations",
    "build_runs",
)
TASK_MUTABLE_TABLES = ("tasks", "work_items", "task_wait_conditions", "task_run_links")
WORKSPACE_INSERTS = {
    "api": ("project_git_sources", "project_source_imports", "workspaces"),
    "worker": ("project_git_sources", "workspace_candidates"),
}
WORKSPACE_RECEIPT_COLUMNS = (
    "workspace_revision", "write_generation", "binding_json", "binding_digest",
    "files_json", "files_digest", "materialization_operation_id", "storage_id",
)
_IDENTITY_UPDATES = {
    "api": {
        "users": ("revision",), "device_sessions": ("revoked_at", "revision"),
        "projects": ("name", "revision"), "project_policies": ("authorization_revision",),
        "role_bindings": ("actions", "revision", "revoked_at"),
        "delegations": ("revoked_at", "revision"),
    },
    "worker": {"users": ("revision",), "project_policies": ("authorization_revision",)},
}


def apply_runtime_permissions(connection: Connection) -> None:
    """Called only by maintenance after the fixed business/DBOS schemas exist."""
    require_maintenance_role(connection)
    for role in ("api", "worker"):
        name = ROLE_NAMES[role]
        connection.exec_driver_sql(f"REVOKE ALL ON SCHEMA cloudhelm FROM {name}")
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA cloudhelm TO {name}")
        connection.exec_driver_sql(f"REVOKE ALL ON ALL TABLES IN SCHEMA cloudhelm FROM {name}")
        connection.exec_driver_sql(f"GRANT SELECT ON ALL TABLES IN SCHEMA cloudhelm TO {name}")
        for table in (*IMMUTABLE_TABLES, *TASK_MUTABLE_TABLES, "outbox", "task_fact_sources"):
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
        for table in TASK_MUTABLE_TABLES:
            connection.exec_driver_sql(f"GRANT UPDATE ON cloudhelm.{table} TO {name}")
        for table, columns in {**_IDENTITY_UPDATES[role], "outbox": ("dispatched_at",),
                               "task_fact_sources": ("enabled",)}.items():
            connection.exec_driver_sql(f"GRANT UPDATE ({', '.join(columns)}) ON cloudhelm.{table} TO {name}")
        for table in WORKSPACE_INSERTS[role]:
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
        if role == "worker":
            connection.exec_driver_sql(
                f"GRANT UPDATE ({', '.join(WORKSPACE_RECEIPT_COLUMNS)}) ON cloudhelm.workspaces TO {name}"
            )
        if role == "api":
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.role_bindings TO {name}")
    connection.exec_driver_sql(f"REVOKE ALL ON ALL TABLES IN SCHEMA dbos FROM {DBOS_RUNTIME_ROLE}")
    connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA dbos TO {DBOS_RUNTIME_ROLE}")
    connection.exec_driver_sql(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA dbos FROM {DBOS_RUNTIME_ROLE}")
    connection.exec_driver_sql(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA dbos TO {DBOS_RUNTIME_ROLE}")
    connection.exec_driver_sql(f"REVOKE INSERT, UPDATE, DELETE ON dbos.dbos_migrations FROM {DBOS_RUNTIME_ROLE}")
    connection.exec_driver_sql(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA dbos REVOKE ALL ON TABLES FROM {DBOS_RUNTIME_ROLE}"
    )
    connection.exec_driver_sql(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA dbos REVOKE ALL ON SEQUENCES FROM {DBOS_RUNTIME_ROLE}"
    )
