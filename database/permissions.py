"""Fixed Hub role grants; no runtime role owns schema or mutable audit history."""

from sqlalchemy.engine import Connection

from database.readiness import ROLE_NAMES, require_maintenance_role

DBOS_RUNTIME_ROLE = "cloudhelm_dbos_runtime"
IMMUTABLE_TABLES = (
    "commands", "event_log", "workflow_bindings", "audit_records", "task_declarations",
    "task_inputs", "task_completion_reports", "task_reference_records", "task_evidence_links",
    "task_operation_links", "task_operation_observations",
    "build_runs",
    "releases", "environment_configs", "deployment_plans", "deployment_approvals", "environment_revisions",
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
WORKSPACE_DEVELOPMENT_INSERTS = {
    "api": ("workspace_development_environments", "workspace_development_environment_operations"),
    "worker": (),
}
WORKSPACE_DEVELOPMENT_CONTROL_COLUMNS = (
    "environment_revision", "workspace_revision", "write_generation", "binding_json", "binding_digest",
    "source_manifest_digest", "updated_at",
)
WORKSPACE_DEVELOPMENT_RECEIPT_COLUMNS = (
    "state", "data_revision", "data_generation", "runtime_fact_json", "health_probe_json",
    "ready_probe_json", "stop_fact_json", "updated_at",
    "workspace_revision", "write_generation", "binding_json", "binding_digest", "source_manifest_digest",
    "original_lock_digest", "dependency_cache_key", "toolchain_json", "toolchain_digest", "migration_revision",
)
WORKSPACE_DEVELOPMENT_OPERATION_RECEIPT_COLUMNS = (
    "operation_state", "observation_json", "observation_digest", "closed_at",
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
        if role == "api":
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.sync_streams, cloudhelm.sync_dispatch_events TO {name}")
            connection.exec_driver_sql(f"GRANT UPDATE (last_cursor) ON cloudhelm.sync_streams TO {name}")
        for table in (*IMMUTABLE_TABLES, *TASK_MUTABLE_TABLES, "outbox", "task_fact_sources"):
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
        connection.exec_driver_sql(f"GRANT INSERT, UPDATE (applicability) ON cloudhelm.verification_dependencies TO {name}")
        connection.exec_driver_sql(f"GRANT INSERT, UPDATE (state, record_json) ON cloudhelm.workspace_handoffs TO {name}")
        connection.exec_driver_sql(f"GRANT INSERT, UPDATE (state, record_json) ON cloudhelm.merge_queue TO {name}")
        connection.exec_driver_sql(f"GRANT USAGE ON SEQUENCE cloudhelm.merge_queue_position_seq TO {name}")
        for table in TASK_MUTABLE_TABLES:
            connection.exec_driver_sql(f"GRANT UPDATE ON cloudhelm.{table} TO {name}")
        for table, columns in {**_IDENTITY_UPDATES[role], "outbox": ("dispatched_at",),
                               "task_fact_sources": ("enabled",)}.items():
            connection.exec_driver_sql(f"GRANT UPDATE ({', '.join(columns)}) ON cloudhelm.{table} TO {name}")
        for table in WORKSPACE_INSERTS[role]:
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
        if role == "worker":
            for table in ("agent_sessions", "agent_runs", "agent_operation_waits"):
                connection.exec_driver_sql(f"GRANT INSERT, UPDATE ON cloudhelm.{table} TO {name}")
            for table in ("agent_histories", "agent_model_requests", "agent_model_request_results"):
                connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
            connection.exec_driver_sql(f"GRANT UPDATE (lock_revision) ON cloudhelm.delivery_remote_credentials TO {name}")
            connection.exec_driver_sql(
                f"GRANT UPDATE ({', '.join(WORKSPACE_RECEIPT_COLUMNS)}) ON cloudhelm.workspaces TO {name}"
            )
            connection.exec_driver_sql(
                f"GRANT UPDATE ({', '.join(WORKSPACE_DEVELOPMENT_RECEIPT_COLUMNS)}) "
                "ON cloudhelm.workspace_development_environments TO " + name
            )
            connection.exec_driver_sql(
                f"GRANT UPDATE ({', '.join(WORKSPACE_DEVELOPMENT_OPERATION_RECEIPT_COLUMNS)}) "
                "ON cloudhelm.workspace_development_environment_operations TO " + name
            )
        if role == "api":
            connection.exec_driver_sql(
                f"GRANT UPDATE ({', '.join(WORKSPACE_DEVELOPMENT_CONTROL_COLUMNS)}) "
                "ON cloudhelm.workspace_development_environments TO " + name
            )
        for table in WORKSPACE_DEVELOPMENT_INSERTS[role]:
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
        connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.resource_reservations TO {name}")
        connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.resource_adjustments TO {name}")
        # PostgreSQL requires UPDATE on at least one column for SELECT FOR
        # UPDATE. Capacity and registration columns remain maintenance-only.
        connection.exec_driver_sql(f"GRANT UPDATE (lock_revision) ON cloudhelm.resource_pools TO {name}")
        if role == "worker":
            connection.exec_driver_sql(
                "GRANT UPDATE (allocation_json, receipt_json, receipt_sequence) "
                f"ON cloudhelm.resource_reservations TO {name}"
            )
        if role == "api":
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.role_bindings TO {name}")
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.environment_bindings TO {name}")
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.deployment_closeouts TO {name}")
            connection.exec_driver_sql(
                "GRANT UPDATE (config_revision, active_operation_id, release_id, config_revision_id) "
                f"ON cloudhelm.environment_bindings TO {name}"
            )
        if role == "worker":
            for table in ("delivery_remote_samples", "delivery_remote_grants", "delivery_remote_results",
                          "delivery_remote_closeouts"):
                connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.{table} TO {name}")
            connection.exec_driver_sql(f"GRANT INSERT ON cloudhelm.delivery_target_observations TO {name}")
            connection.exec_driver_sql("GRANT UPDATE (environment_revision, release_id, config_revision_id, active_operation_id) "
                                      f"ON cloudhelm.environment_bindings TO {name}")
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
