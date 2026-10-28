"""Runner queried observations; the Hub never accepts caller supplied physical facts."""

from dataclasses import dataclass, field
import hashlib
from importlib import import_module

import rfc8785
from sqlalchemy import func, select, update

from database.commands import get_by_id
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.sync.events import append_event
from modules.sync.tables import event_log
from modules.workspaces.development_queries import (
    WorkspaceDevelopmentError, read_development_environment,
    read_development_operation_record,
)
from modules.workspaces.development_tables import (
    workspace_development_environment_operations as operation_table,
    workspace_development_environments as environment_table,
)
from modules.workspaces.operations import read_workspace_row
from packages.contracts.p1.development_environment import WorkspaceDevelopmentEnvironmentObservation
from packages.contracts.p1.workspace_records import workspace_metadata_digest

OBSERVATION_SCHEMA = "p1-workspace-development-observation-event-r1"
_VERIFIED = object()


def observation_digest(observation):
    return "sha256:" + hashlib.sha256(rfc8785.dumps(observation.model_dump(mode="json"))).hexdigest()


@dataclass(frozen=True, slots=True)
class _VerifiedDevelopmentObservation:
    operation_id: str
    observation: WorkspaceDevelopmentEnvironmentObservation
    digest: str
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self._proof is not _VERIFIED:
            raise WorkspaceDevelopmentError("workspace_development_verified_observation_required")


def verify_development_observation(operation_id, runtime):
    """Read only through the concrete C5 Controller; never wrap an arbitrary object."""
    try:
        controller_module = import_module("services.dev-runner.workspace_development_lifecycle")
        WorkspaceDevelopmentController = controller_module.WorkspaceDevelopmentController
    except ImportError:
        raise WorkspaceDevelopmentError("workspace_development_controller_unavailable") from None
    if type(runtime) is not WorkspaceDevelopmentController:
        raise WorkspaceDevelopmentError("workspace_development_controller_required")
    try:
        raw = runtime.query(operation_id)
        if type(raw) is not WorkspaceDevelopmentEnvironmentObservation:
            raise ValueError
        observation = WorkspaceDevelopmentEnvironmentObservation.model_validate(raw.model_dump(mode="python"))
        _runner_identity(observation)
    except Exception:
        raise WorkspaceDevelopmentError("workspace_development_observation_unavailable") from None
    return _VerifiedDevelopmentObservation(operation_id, observation, observation_digest(observation), _VERIFIED)


def _runner_identity(observation):
    identities = [
        fact.runner for fact in (
            observation.runtime_fact, observation.health_probe, observation.ready_probe, observation.stop_fact,
        ) if fact is not None
    ]
    if not identities or any(value != identities[0] for value in identities[1:]):
        raise WorkspaceDevelopmentError("workspace_development_runner_identity_missing")
    return identities[0]


def _check_observation(intent, verified):
    request, observation = intent.request, verified.observation
    binding_matches = observation.binding == request.binding
    if request.action in {"suspend", "dispose"}:
        binding_matches = all(
            getattr(observation.binding, field) == getattr(request.binding, field)
            for field in ("workspace_id", "project_id", "task_id", "work_item_id", "owner_user_id", "source_id",
                          "source_revision")
        )
    if not all((
        verified.operation_id == request.operation_id == observation.operation_id,
        observation.environment_id == request.environment_id,
        observation.request_digest == intent.request_digest,
        observation.profile_revision == "notes-backend-dev-r1",
        binding_matches,
        observation.storage_ref.purpose == "workspace",
    )):
        raise WorkspaceDevelopmentError("workspace_development_observation_binding_mismatch")
    if request.action not in {"suspend", "dispose"} and observation.source_manifest_digest != request.source_manifest_digest:
        raise WorkspaceDevelopmentError("workspace_development_observation_source_mismatch")
    if request.action == "prepare":
        spec = request.spec
        if (observation.storage_ref != spec.storage_ref or observation.migration_revision != spec.migration_revision
                or observation.data_revision != spec.data_revision):
            raise WorkspaceDevelopmentError("workspace_development_observation_input_mismatch")
    elif request.action == "resume":
        spec = request.spec
        if (observation.storage_ref != spec.storage_ref or observation.migration_revision != spec.migration_revision
                or observation.data_revision != spec.data_revision
                or observation.data_generation != request.expected_data_generation):
            raise WorkspaceDevelopmentError("workspace_development_observation_input_mismatch")
    elif request.action in {"suspend", "dispose"}:
        if observation.storage_ref.purpose != "workspace":
            raise WorkspaceDevelopmentError("workspace_development_observation_input_mismatch")
    elif request.action == "reset_data":
        if observation.state == "ready":
            if observation.data_generation <= request.expected_data_generation:
                raise WorkspaceDevelopmentError("workspace_development_observation_generation_not_advanced")
            if observation.data_revision != request.target_data_revision:
                raise WorkspaceDevelopmentError("workspace_development_observation_data_revision_mismatch")
    return observation


def _operation_state(request, observation):
    if observation.state == "failed":
        stopped = (
            observation.stop_fact is not None and observation.stop_fact.outcome == "confirmed_stopped"
            or observation.runtime_fact is not None and observation.runtime_fact.status == "stopped"
        )
        return "failed" if stopped else "unknown"
    target = {
        "prepare": "ready", "suspend": "suspended", "resume": "ready",
        "reset_data": "ready", "dispose": "disposed",
    }[request.action]
    return "succeeded" if observation.state == target else "unknown"


def register_verified_observation_in_uow(uow, operation_id, verified):
    require_transaction(uow.connection)
    if type(verified) is not _VerifiedDevelopmentObservation or verified._proof is not _VERIFIED:
        raise WorkspaceDevelopmentError("workspace_development_verified_observation_required")
    if verified.operation_id != operation_id:
        raise WorkspaceDevelopmentError("workspace_development_observation_binding_mismatch")
    intent, _, operation, _, _ = read_development_operation_record(uow.connection, operation_id)
    observation = _check_observation(intent, verified)
    actor = actor_for_command(uow, operation["command_id"])
    task, authorization = lock_task_access(uow, actor, operation["task_id"], "workspace.write")
    authorize_current(uow, actor, AuthoritativeResource(
        operation["project_id"], "operation", operation_id, task_id=operation["task_id"],
    ), "operation.query")
    workspace = read_workspace_row(uow.connection, operation["workspace_id"], for_update=True)
    environment = read_development_environment(uow.connection, operation["environment_id"], for_update=True)
    if (task["project_id"] != operation["project_id"] or workspace["task_id"] != task["task_id"]
            or environment["task_id"] != task["task_id"] or environment["workspace_id"] != workspace["workspace_id"]):
        raise WorkspaceDevelopmentError("workspace_development_scope_mismatch")
    if observation.storage_ref.model_dump(mode="json") != environment["storage_ref_json"]:
        raise WorkspaceDevelopmentError("workspace_development_observation_storage_mismatch")
    existing_digest = operation["observation_digest"]
    if existing_digest == verified.digest:
        return observation
    if existing_digest is not None and operation["operation_state"] in {"succeeded", "failed"}:
        raise WorkspaceDevelopmentError("workspace_development_physical_digest_conflict")
    if (operation["operation_state"] not in {"pending", "unknown"}
            or environment["environment_revision"] != intent.accepted_environment_revision):
        if existing_digest == verified.digest:
            return observation
        raise WorkspaceDevelopmentError("workspace_development_operation_not_pending")
    state = _operation_state(intent.request, observation)
    closed = state in {"succeeded", "failed"}
    identity = _runner_identity(observation)
    event_id = "workspace-development-observation-" + identity.observation_id
    prior = uow.connection.execute(select(event_log).where(event_log.c.event_id == event_id)).mappings().one_or_none()
    if prior is not None:
        try:
            prior_observation = WorkspaceDevelopmentEnvironmentObservation.model_validate(prior["payload"])
        except ValueError:
            raise WorkspaceDevelopmentError("workspace_development_observation_event_invalid") from None
        if observation_digest(prior_observation) == verified.digest:
            return observation
        raise WorkspaceDevelopmentError("workspace_development_physical_digest_conflict")
    observed_at = observation.model_dump(mode="json")
    result = uow.connection.execute(update(operation_table).where(
        operation_table.c.operation_id == operation_id,
        operation_table.c.operation_state.in_(("pending", "unknown")),
    ).values(
        operation_state=state, observation_json=observed_at, observation_digest=verified.digest,
        closed_at=func.now() if closed else None,
    ))
    if result.rowcount != 1:
        raise WorkspaceDevelopmentError("workspace_development_operation_conflict")
    values = dict(
        workspace_revision=observation.binding.workspace_revision,
        write_generation=observation.binding.write_generation,
        binding_json=observation.binding.model_dump(mode="json"),
        binding_digest=workspace_metadata_digest(observation.binding),
        source_manifest_digest=observation.source_manifest_digest,
        migration_revision=observation.migration_revision, data_revision=observation.data_revision,
        data_generation=observation.data_generation, state=observation.state,
        runtime_fact_json=(observation.runtime_fact.model_dump(mode="json") if observation.runtime_fact else None),
        health_probe_json=(observation.health_probe.model_dump(mode="json") if observation.health_probe else None),
        ready_probe_json=(observation.ready_probe.model_dump(mode="json") if observation.ready_probe else None),
        stop_fact_json=(observation.stop_fact.model_dump(mode="json") if observation.stop_fact else None),
        updated_at=func.now(),
    )
    if intent.request.action == "resume" and state == "succeeded":
        spec = intent.request.spec
        values.update(
            original_lock_digest=spec.original_lock_digest, dependency_cache_key=spec.dependency_cache_key,
            toolchain_json=spec.toolchain.model_dump(mode="json"), toolchain_digest=spec.toolchain.artifact_digest,
        )
    environment_result = uow.connection.execute(update(environment_table).where(
        environment_table.c.environment_id == operation["environment_id"],
        environment_table.c.environment_revision == intent.accepted_environment_revision,
    ).values(**values))
    if environment_result.rowcount != 1:
        raise WorkspaceDevelopmentError("workspace_development_revision_conflict")
    context = TaskCommandContext(
        uow, actor, task, authorization, get_by_id(uow.connection, operation["command_id"]).envelope,
    )
    update_task(context, operation_set_revision=task["operation_set_revision"] + 1)
    append_event(
        uow.connection, command_id=operation["command_id"], project_id=operation["project_id"],
        aggregate_kind="workspace_development_environment", aggregate_id=operation["environment_id"],
        aggregate_version=intent.accepted_environment_revision, event_type="workspace.development_observed",
        schema_version=OBSERVATION_SCHEMA,
        event_id=event_id,
        payload=observation,
    )
    return observation


def register_development_observation(engine, operation_id, runtime, *, notify=None):
    verified = verify_development_observation(operation_id, runtime)
    with UnitOfWork(engine) as uow:
        observation = register_verified_observation_in_uow(uow, operation_id, verified)
        if notify is not None:
            notify(uow, operation_id)
        return observation
