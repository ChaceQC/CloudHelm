"""Bounded local DBOS runtime; business workflow implementations stay in their domain."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from threading import Event

from dbos import DBOS, DBOSClient, DBOSConfig, DBOSPortableJSONSerializer

from database.connection import create_business_pools, create_engine_from_settings
from database.readiness import assert_runtime_ready
from database.settings import load_database_settings
from database.uow import UnitOfWork
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, DBOS_SCHEMA, WORKFLOW_QUEUES

from .process_lock import acquire_worker_process_lock

WORKER_QUEUES = tuple(sorted({*WORKFLOW_QUEUES.values(), "models"}))
MAX_EXECUTOR_THREADS = 4


class WorkerRuntimeError(RuntimeError):
    pass


def emit_status(status: str, **fields: str | int) -> None:
    print(json.dumps({"status": status, "time": datetime.now(timezone.utc).isoformat(),
                      **fields}, ensure_ascii=False), flush=True)


def _local_environment() -> None:
    # Check names only; do not read inherited DBOS credentials or cloud overrides.
    if any(name.startswith("DBOS_") for name in os.environ):
        raise WorkerRuntimeError("external_dbos_environment_not_supported")


def _start_dbos(application, engine, installation_id: str, engineering, agent_runtime) -> None:
    from modules.collaboration.workflows import register_task_workflows
    from modules.delivery.workflows import register_build_workflows
    from modules.delivery.deployment_workflows import register_deployment_workflows
    from modules.projects.workflows import register_source_workflows
    from modules.workspaces.workflows import register_workspace_workflows
    from modules.workspaces.development_workflows import register_development_environment_workflows
    from modules.agent_runtime.workflows import register_agent_workflows

    DBOS(config=DBOSConfig(
        name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
        executor_id=f"cloudhelm-hub-{installation_id}", system_database_engine=engine,
        dbos_system_schema=DBOS_SCHEMA, run_migrations=False,
        serializer=DBOSPortableJSONSerializer(), use_listen_notify=True,
        max_executor_threads=MAX_EXECUTOR_THREADS, sys_db_polling_concurrency=1,
        enable_otlp=False, enable_patching=False,
        log_level="CRITICAL", console_log_level="CRITICAL",
    ))
    register_task_workflows(application)
    register_source_workflows(engineering.source_import)
    register_workspace_workflows(engineering.workspace_operation)
    register_build_workflows(engineering.build)
    register_deployment_workflows(application.control_engine)
    register_development_environment_workflows(engineering.development_environment)
    register_agent_workflows(agent_runtime)
    DBOS.listen_queues(WORKER_QUEUES)
    DBOS.launch()
    for queue in WORKER_QUEUES:
        DBOS.register_queue(queue, worker_concurrency=1, global_concurrency=1,
                            polling_interval_sec=1.0)


def run_worker(stop: Event, *, shutdown_grace_seconds: int = 10) -> None:
    """Process entry only. No API imports, schema migration, lease or forced takeover."""
    if not 0 <= shutdown_grace_seconds <= 30:
        raise WorkerRuntimeError("worker_shutdown_grace_invalid")
    logging.disable(logging.CRITICAL)
    _local_environment()
    settings = load_database_settings("worker")
    pools = create_business_pools(settings)
    client = None
    system_engine = None
    engineering = None
    dbos_attempted = False
    try:
        with UnitOfWork(pools.control) as uow:
            baseline = assert_runtime_ready(uow.connection, role="worker")
        acquire_worker_process_lock(baseline.installation_id)
        with UnitOfWork(pools.control) as uow:
            current = assert_runtime_ready(uow.connection, role="worker")
            if current != baseline:
                raise WorkerRuntimeError("worker_installation_changed_during_startup")
        if stop.is_set():
            return
        from modules.collaboration.application import TaskApplication
        from .engineering_runtime import create_engineering_runtime

        client = DBOSClient(
            system_database_engine=pools.normal, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False,
            system_database_polling_concurrency=1, observability_query_timeout_sec=5,
        )
        system_engine = create_engine_from_settings(settings, purpose="dbos")
        application = TaskApplication(pools.normal, pools.control, client)
        engineering = create_engineering_runtime(pools)
        from modules.agent_runtime.application import AgentRuntimeApplication
        from modules.agent_runtime.provider import configured_provider
        agent_runtime = AgentRuntimeApplication(pools.normal, client, configured_provider())
        dbos_attempted = True
        _start_dbos(application, system_engine, baseline.installation_id, engineering, agent_runtime)
        if not stop.is_set():
            emit_status("ready", installation_id=baseline.installation_id,
                        application_name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
                        pid=os.getpid())
            stop.wait()
        emit_status("shutdown_requested")
    finally:
        try:
            if dbos_attempted:
                DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=shutdown_grace_seconds)
        finally:
            try:
                if engineering is not None:
                    engineering.close()
            finally:
                if client is not None:
                    client.destroy()
                if system_engine is not None:
                    system_engine.dispose()
                pools.dispose()
