"""Current work item support, without probing physical execution or deciding readiness."""

from collections.abc import Mapping
from importlib import import_module
from typing import Any, Protocol

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import task_resource
from modules.collaboration.records import read_fact_source, read_registered_reference
from modules.execution.tables import resource_pools, resource_runners
from modules.identity.actors import Actor, AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.projects.source_import_tables import project_source_imports
from modules.projects.source_operations import SourceImportError
from modules.projects.source_receipts import read_source_registration
from modules.workspaces.preview_environments import PreviewInstallation
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import Action
from packages.contracts.p0.preview_contracts import check_client_route
from packages.contracts.p0.resource_contracts import ResourceVector
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.resource_protocol import (
    DEVELOPMENT_BACKEND, STORAGE_BACKEND, PoolRegistration, RunnerRegistration,
)
from packages.contracts.p1.task_facts import HumanPolicyMetadata, ResourcePolicyMetadata
from packages.contracts.p2.work_item_capabilities import WorkItemCapabilities, WorkItemCapability
from packages.contracts.p2.work_item_run import WorkItemRequirements


class _EngineeringRegistration(Protocol):
    """Subset of the trusted, validated installation registry used by the Hub."""

    scope: str
    storage: DevelopmentStorageRef
    resource_runner_id: str | None
    storage_runner_id: str | None
    storage_owner_reservation_id: str | None


def _current_permission(uow: UnitOfWork, actor: Actor, resource: AuthoritativeResource, action: Action) -> bool:
    try:
        authorize_current(uow, actor, resource, action)
    except IdentityError as error:
        if error.code not in {"permission_denied", "delegation_not_current"}:
            raise
        return False
    return True


def _registered_source_reason(connection, project_id: str, source_ref: EngineeringRef) -> str:
    row = connection.execute(select(project_source_imports).where(
        project_source_imports.c.project_id == project_id,
    )).mappings().one_or_none()
    try:
        registration = read_source_registration(connection, row) if row is not None else None
    except SourceImportError:
        return "managed_source_registration_invalid"
    if registration is None:
        return "managed_source_not_registered"
    source = registration.source_record.source
    if registration.source_ref != source_ref or source.project_id != project_id:
        return "managed_source_declaration_mismatch"
    if source.access_mode != "read_write":
        return "managed_source_read_only"
    return "managed_source_registered"


def _registered_runner(
    uow: UnitOfWork, registration: _EngineeringRegistration | None,
) -> tuple[RunnerRegistration, PoolRegistration] | None:
    if registration is None or registration.resource_runner_id is None:
        return None
    rows = uow.connection.execute(select(
        resource_runners.c.executor_instance_id,
        resource_runners.c.registration_json,
        resource_pools.c.registration_json.label("pool_json"),
    ).select_from(resource_runners.join(resource_pools)).where(resource_runners.c.executor_instance_id.in_(
        (registration.resource_runner_id, registration.storage_runner_id),
    ))).mappings()
    registered = {row["executor_instance_id"]: row for row in rows}
    process_row = registered.get(registration.resource_runner_id)
    storage_row = registered.get(registration.storage_runner_id)
    if process_row is None or storage_row is None:
        return None
    process = RunnerRegistration.model_validate(process_row["registration_json"])
    storage = RunnerRegistration.model_validate(storage_row["registration_json"])
    pool = PoolRegistration.model_validate(process_row["pool_json"])
    if (process.backend != DEVELOPMENT_BACKEND or storage.backend != STORAGE_BACKEND
            or process.storage != registration.storage or storage.storage != registration.storage
            or process.storage_owner_reservation_id != registration.storage_owner_reservation_id
            or process.host_resource_pool_id != storage.host_resource_pool_id
            or any(r.executor_instance_id not in pool.pool.executor_instance_ids
                   or r.physical_host_id != pool.pool.physical_host_id
                   or r.hub_incarnation != pool.hub_incarnation
                   or r.resource_generation != pool.resource_generation for r in (process, storage))):
        return None
    return process, pool


def _supports_envelope(
    registration: tuple[RunnerRegistration, PoolRegistration], *, preview: bool,
) -> bool:
    # The worker requests these same fixed envelopes. No current allocation is read.
    profiles = import_module("services.dev-runner.resource_development")
    envelope = profiles.PREVIEW_ENVELOPE if preview else profiles.ENVELOPE
    runner, pool = registration
    return all(ceiling is not None
               and all(getattr(envelope, key) <= getattr(ceiling, key) for key in ResourceVector.model_fields)
               for ceiling in (runner.maximum, pool.pool.configured_budget, pool.pool.measured_allocatable_capacity))


def _formal_preview_support(
    installation: PreviewInstallation | None, runner: tuple[RunnerRegistration, PoolRegistration] | None,
) -> WorkItemCapability:
    if installation is None:
        return WorkItemCapability(available=False, reason="formal_preview_not_registered")
    route = installation.client_route
    try:
        check_client_route(route)
    except ValueError:
        return WorkItemCapability(available=False, reason="formal_preview_isolation_evidence_invalid")
    if runner is None:
        return WorkItemCapability(available=False, reason="formal_preview_runner_not_registered")
    if not _supports_envelope(runner, preview=True):
        return WorkItemCapability(available=False, reason="formal_preview_runner_limits_unsupported")
    return WorkItemCapability(available=True, reason="formal_preview_support_registered",
                              evidence_refs=tuple(item.evidence_ref for item in route.isolation_evidence),
                              runner_evidence_ref=runner[0].capability_evidence_ref)


def require_formal_preview_in_uow(
    uow: UnitOfWork, requirements: WorkItemRequirements, *,
    engineering_registration: _EngineeringRegistration | None, preview_installation: PreviewInstallation | None,
) -> None:
    """Check installation support only when the work item explicitly requires it."""
    if not requirements.formal_preview_required:
        return
    runner = _registered_runner(uow, engineering_registration) if preview_installation is not None else None
    support = _formal_preview_support(preview_installation, runner)
    if not support.available:
        raise TaskBoundaryError(support.reason)


def _product_policy(connection, project_id: str, reference: EngineeringRef, metadata_type):
    try:
        record = read_registered_reference(connection, project_id, reference)
        if (isinstance(record.metadata, metadata_type)
                and read_fact_source(connection, project_id, record.source_id).purpose == "product"):
            return record.metadata
    except TaskBoundaryError:
        return None
    return None


def _build_support(uow, actor, task, declaration, source_reason, registration, runner) -> WorkItemCapability:
    if not _current_permission(uow, actor, task_resource(task), "operation.request"):
        return WorkItemCapability(available=False, reason="operation_request_not_authorized")
    if source_reason != "managed_source_registered":
        return WorkItemCapability(available=False, reason=source_reason)
    if registration is None:
        return WorkItemCapability(available=False, reason="reference_build_recipe_not_registered")
    # The Projects registration vouches for the fixed reference source; the validated
    # installation registration is restricted to that reference's controlled build seeds.
    policy_ref = declaration.resource_scope_ref
    policy = _product_policy(uow.connection, task["project_id"], policy_ref, ResourcePolicyMetadata)
    if (policy is None or registration.scope not in policy.resource_scope_ids
            or "operation.request" not in policy.allowed_capabilities):
        return WorkItemCapability(available=False, reason="reference_build_resource_scope_unavailable",
                                  policy_ref=policy_ref)
    if runner is None:
        return WorkItemCapability(available=False, reason="reference_build_runner_not_registered", policy_ref=policy_ref)
    if not _supports_envelope(runner, preview=False):
        return WorkItemCapability(available=False, reason="reference_build_runner_limits_unsupported", policy_ref=policy_ref)
    return WorkItemCapability(available=True, reason="reference_build_support_registered",
                              evidence_refs=(declaration.source_ref,), policy_ref=policy_ref,
                              runner_evidence_ref=runner[0].capability_evidence_ref)


def project_work_item_capabilities_in_uow(
    uow: UnitOfWork, actor: Actor, task: Mapping[str, Any], item: Mapping[str, Any], *,
    authorization_revision: int, engineering_registration: _EngineeringRegistration | None,
    preview_installation: PreviewInstallation | None,
) -> WorkItemCapabilities:
    """Caller holds current Task read access; domain commands still reauthorize every action."""
    project_id = task["project_id"]
    declaration = read_declaration(uow.connection, task)
    requirements = WorkItemRequirements.model_validate(item["run_requirements_json"])
    source_reason = _registered_source_reason(uow.connection, project_id, declaration.source_ref)
    if not _current_permission(uow, actor, task_resource(task), "workspace.write"):
        managed_source = WorkItemCapability(available=False, reason="workspace_write_not_authorized")
    elif source_reason != "managed_source_registered":
        managed_source = WorkItemCapability(available=False, reason=source_reason)
    else:
        managed_source = WorkItemCapability(available=True, reason=source_reason, evidence_refs=(declaration.source_ref,))
    runner = _registered_runner(uow, engineering_registration)
    build = _build_support(uow, actor, task, declaration, source_reason, engineering_registration, runner)
    preview = _formal_preview_support(preview_installation, runner)
    human_ref = declaration.human_test_policy_ref
    human_policy = _product_policy(uow.connection, project_id, human_ref, HumanPolicyMetadata)
    human_required = human_policy is not None and human_policy.is_completion_gate
    skip_allowed = human_policy.skip_allowed if human_policy is not None else None
    preview_phase = ("start" if requirements.formal_preview_required else
                     "completion" if human_required and not skip_allowed else "none")
    preview = preview.model_copy(update={"gate_phase": preview_phase,
                                        "policy_ref": human_ref if preview_phase == "completion" else None})
    human_test = WorkItemCapability(
        available=human_policy is not None and preview.available,
        reason=("human_test_policy_unavailable" if human_policy is None else
                "human_test_formal_preview_unavailable" if not preview.available else
                "human_test_required" if human_required else "human_test_optional"),
        gate_phase="completion" if human_policy is None or human_required else "none", policy_ref=human_ref,
    )
    return WorkItemCapabilities(task_id=task["task_id"], work_item_id=item["work_item_id"],
        work_item_revision=item["revision"], authorization_revision=authorization_revision,
        prerequisites=requirements.prerequisites, managed_source=managed_source,
        build=build, formal_preview=preview, human_test=human_test, human_test_skip_allowed=skip_allowed)
