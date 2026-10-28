"""API-only startup: bounded pools and a client, never a workflow runtime."""

from dataclasses import dataclass, field
from uuid import uuid4
from pathlib import Path
from typing import TYPE_CHECKING

from database.connection import BusinessPools, create_business_pools
from database.readiness import assert_runtime_ready
from database.settings import DatabaseSettings, load_database_settings
from database.uow import UnitOfWork
from modules.projects.commands import ProjectApplication
from modules.execution.application import ResourceApplication
from modules.integration.candidates import FixedCandidateApplication
from modules.integration.verification import VerificationApplication
from modules.integration.validity import VerificationImpactApplication
from modules.workspaces.handoffs import WorkspaceHandoffApplication
from modules.delivery.deployment_application import DeliveryApplication
from modules.workflow.version import APPLICATION_NAME, DBOS_SCHEMA

if TYPE_CHECKING:
    from dbos import DBOSClient
    from modules.collaboration.application import TaskApplication
    from modules.collaboration.reference_inputs import ReferenceTaskApplication
    from modules.delivery.commands import BuildApplication
    from modules.projects.source_commands import SourceImportApplication
    from modules.workspaces.application import WorkspaceApplication
    from modules.workspaces.development_application import WorkspaceDevelopmentApplication


class ApiStartupError(RuntimeError):
    """The original SDK/configuration/driver exception is intentionally hidden."""


@dataclass(slots=True, repr=False)
class ApiRuntime:
    pools: BusinessPools
    client: "DBOSClient"
    projects: ProjectApplication
    tasks: "TaskApplication"
    sources: "SourceImportApplication"
    reference_tasks: "ReferenceTaskApplication"
    workspaces: "WorkspaceApplication"
    builds: "BuildApplication"
    development: "WorkspaceDevelopmentApplication"
    resources: ResourceApplication
    delivery: DeliveryApplication
    candidates: FixedCandidateApplication
    verifications: VerificationApplication
    verification_impacts: VerificationImpactApplication
    handoffs: WorkspaceHandoffApplication
    sync_epoch: str = field(default_factory=lambda: uuid4().hex)

    def close(self) -> None:
        try:
            _cleanup(self.pools, self.client)
        except Exception:
            raise ApiStartupError("api_shutdown_failed") from None


def _cleanup(pools, client) -> None:
    try:
        if client is not None:
            client.destroy()
    finally:
        if pools is not None:
            pools.dispose()


def start_runtime(settings: DatabaseSettings | None = None) -> ApiRuntime:
    """Called by lifespan only; imports and OpenAPI export do not invoke this."""
    pools, client = None, None
    try:
        from dbos import DBOSClient, DBOSPortableJSONSerializer
        from modules.collaboration.application import TaskApplication
        from modules.collaboration.reference_inputs import ReferenceTaskApplication
        from modules.delivery.commands import BuildApplication
        from modules.projects.source_commands import SourceImportApplication
        from modules.workflow.engineering_enqueuers import build_enqueuer, engineering_enqueuer
        from modules.workflow.engineering_enqueuers import development_environment_enqueuer
        from modules.workspaces.application import WorkspaceApplication
        from modules.workspaces.development_application import WorkspaceDevelopmentApplication
        from packages.contracts.p1.workspace_candidates import workspace_runtime_scope_id
        from importlib import import_module

        development_registry = import_module("services.dev-runner.workspace_development_registry")

        selected = settings if settings is not None else load_database_settings("api")
        if selected.role != "api":
            raise ApiStartupError("api_database_role_required")
        pools = create_business_pools(selected)
        with UnitOfWork(pools.normal) as uow:
            assert_runtime_ready(uow.connection, role="api")
        with UnitOfWork(pools.control) as uow:
            assert_runtime_ready(uow.connection, role="api")
        client = DBOSClient(
            system_database_engine=pools.normal, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False,
            system_database_polling_concurrency=1, observability_query_timeout_sec=5,
        )
        return ApiRuntime(
            pools=pools, client=client, projects=ProjectApplication(pools.normal),
            tasks=TaskApplication(pools.normal, pools.control, client),
            sources=SourceImportApplication(pools.normal, pools.control,
                                            enqueue_operation=engineering_enqueuer(client, "project")),
            reference_tasks=ReferenceTaskApplication(pools.normal, Path(__file__).resolve().parents[2]),
            workspaces=WorkspaceApplication(pools.normal, pools.control,
                runtime_scope_for=workspace_runtime_scope_id,
                enqueue_operation=engineering_enqueuer(client, "workspace")),
            builds=BuildApplication(pools.normal, pools.control, enqueue_operation=build_enqueuer(client)),
            development=WorkspaceDevelopmentApplication(
                pools.normal, pools.control, prepared_spec_for=development_registry.registered_development_spec,
                enqueue_operation=development_environment_enqueuer(client),
            ),
            resources=ResourceApplication(pools.normal, pools.control),
            delivery=DeliveryApplication(pools.normal, pools.control,
                enqueue_deployment=engineering_enqueuer(client, "deployment")),
            candidates=FixedCandidateApplication(pools.normal, pools.control),
            verifications=VerificationApplication(pools.normal, pools.control, Path(__file__).resolve().parents[2]),
            verification_impacts=VerificationImpactApplication(pools.normal),
            handoffs=WorkspaceHandoffApplication(pools.normal, pools.control,
                enqueue_operation=engineering_enqueuer(client, "workspace")),
        )
    except Exception:
        try:
            _cleanup(pools, client)
        except Exception:
            pass
        raise ApiStartupError("api_startup_failed") from None
