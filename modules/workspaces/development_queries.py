"""Authorized reads and current-authority gates for Workspace environments."""

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.engine import Connection

from database.commands import get_by_id
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import require_ordinary_progress
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.sync.tables import event_log
from modules.workspaces.development_tables import (
    workspace_development_environment_operations as operation_table,
    workspace_development_environments as environment_table,
)
from modules.workspaces.operations import current_engineering_input, read_workspace_row
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import request_digest
from packages.contracts.p0.task_control_contracts import OperationClosureFact
from packages.contracts.p1.development_environment import (
    DisposeWorkspaceDevelopmentEnvironment, PrepareWorkspaceDevelopmentEnvironment,
    ResetWorkspaceDevelopmentData, ResumeWorkspaceDevelopmentEnvironment,
    SuspendWorkspaceDevelopmentEnvironment, WorkspaceDevelopmentEnvironmentOperationIntent,
    WorkspaceDevelopmentEnvironmentObservation, WorkspaceDevelopmentEnvironmentSpec,
    workspace_development_operation_digest,
)
from packages.contracts.p1.workspace_development_requests import (
    DisposeWorkspaceDevelopmentRequest, PrepareWorkspaceDevelopmentRequest,
    ResetWorkspaceDevelopmentDataRequest, ResumeWorkspaceDevelopmentRequest,
    SuspendWorkspaceDevelopmentRequest, WorkspaceDevelopmentCommandResult,
    WorkspaceDevelopmentEnvironmentView, WorkspaceDevelopmentOperationView,
    WorkspaceDevelopmentRequest,
)
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p1.workspace_records import workspace_metadata_digest

DEVELOPMENT_OPERATION_SCHEMA = "p1-workspace-development-operation-r1"
DEVELOPMENT_OPERATION_EVENT = "workspace.development_operation_accepted"
DEVELOPMENT_OPERATION_EVENT_PREFIX = "workspace-development-intent-"
DEVELOPMENT_OPERATION_ACTION = "workspace.write"

_INTERNAL_REQUEST_TYPES = {
    "prepare": PrepareWorkspaceDevelopmentEnvironment,
    "suspend": SuspendWorkspaceDevelopmentEnvironment,
    "resume": ResumeWorkspaceDevelopmentEnvironment,
    "reset_data": ResetWorkspaceDevelopmentData,
    "dispose": DisposeWorkspaceDevelopmentEnvironment,
}
_PUBLIC_REQUEST_TYPES = {
    "prepare": PrepareWorkspaceDevelopmentRequest,
    "suspend": SuspendWorkspaceDevelopmentRequest,
    "resume": ResumeWorkspaceDevelopmentRequest,
    "reset_data": ResetWorkspaceDevelopmentDataRequest,
    "dispose": DisposeWorkspaceDevelopmentRequest,
}


class WorkspaceDevelopmentError(TaskBoundaryError):
    """Public-safe development-environment boundary failures."""


class _ScopedDevelopmentRequest(Contract):
    workspace_id: Identifier | None
    environment_id: Identifier | None
    request: WorkspaceDevelopmentRequest


@dataclass(frozen=True, slots=True)
class DevelopmentOperationAccess:
    intent: WorkspaceDevelopmentEnvironmentOperationIntent
    client_request: WorkspaceDevelopmentRequest
    task: Mapping[str, Any]
    workspace: Mapping[str, Any]
    environment: Mapping[str, Any]
    authorization: Any
    reconciliation_only: bool


def _parse_request(action: str, raw: Mapping[str, Any], request_types):
    model = request_types.get(action)
    if model is None:
        raise ValueError
    return model.model_validate(raw)


def development_command_digest(envelope, request, *, workspace_id=None, environment_id=None):
    body = _ScopedDevelopmentRequest(
        workspace_id=workspace_id, environment_id=environment_id, request=request,
    )
    return request_digest(envelope, body)


def read_development_environment(connection: Connection, environment_id: str, *, for_update=False):
    require_transaction(connection)
    if for_update:
        # Keep the API role's read-only table grant while serializing changes after Task lock.
        import hashlib

        import rfc8785
        from sqlalchemy import func

        digest = hashlib.sha256(rfc8785.dumps(["cloudhelm.workspace-development-environment.v1", environment_id])).digest()
        connection.execute(select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True))))
    row = connection.execute(select(environment_table).where(
        environment_table.c.environment_id == environment_id,
    )).mappings().one_or_none()
    if row is None:
        raise WorkspaceDevelopmentError("workspace_development_environment_not_found", status_code=404)
    return row


def read_development_operation_record(connection: Connection, operation_id: str):
    """Validate the command, event, and ledger row that jointly define one intent."""
    require_transaction(connection)
    row = connection.execute(select(operation_table).where(
        operation_table.c.operation_id == operation_id,
    )).mappings().one_or_none()
    if row is None:
        raise WorkspaceDevelopmentError("workspace_development_operation_not_found", status_code=404)
    command = get_by_id(connection, row["command_id"])
    event = connection.execute(select(event_log).where(
        event_log.c.event_id == DEVELOPMENT_OPERATION_EVENT_PREFIX + row["command_id"],
    )).mappings().one_or_none()
    if command is None or event is None:
        raise WorkspaceDevelopmentError("workspace_development_operation_invalid")
    try:
        stored = dict(row["request_json"])
        client_raw = stored.pop("client_request")
        internal_request = _parse_request(row["action"], stored, _INTERNAL_REQUEST_TYPES)
        client_request = _parse_request(row["action"], client_raw, _PUBLIC_REQUEST_TYPES)
        intent = WorkspaceDevelopmentEnvironmentOperationIntent.model_validate(event["payload"])
        result = WorkspaceDevelopmentCommandResult.model_validate(command.result)
        envelope = command.envelope
        request = intent.request
        binding = request.binding
        expected_data_revision = (request.spec.data_revision if type(request) is PrepareWorkspaceDevelopmentEnvironment
                                  else request.expected_data_revision)
        expected_data_generation = (request.spec.data_generation if type(request) is PrepareWorkspaceDevelopmentEnvironment
                                    else request.expected_data_generation)
        scope_ok = (
            envelope.scope.project_id == row["project_id"]
            and envelope.scope.resource_kind == "task" and envelope.scope.resource_id == row["task_id"]
            and envelope.target == envelope.scope and envelope.action == DEVELOPMENT_OPERATION_ACTION
        )
        if not all((
            type(internal_request) is type(intent.request), internal_request == request,
            row["operation_id"] == request.operation_id == operation_id,
            row["environment_id"] == request.environment_id,
            row["action"] == request.action,
            row["project_id"] == binding.project_id and row["task_id"] == binding.task_id,
            row["workspace_id"] == binding.workspace_id,
            row["workspace_revision"] == binding.workspace_revision,
            row["write_generation"] == binding.write_generation,
            row["binding_json"] == binding.model_dump(mode="json"),
            row["binding_digest"] == workspace_metadata_digest(binding),
            row["source_manifest_digest"] == request.source_manifest_digest,
            row["request_digest"] == intent.request_digest == workspace_development_operation_digest(request),
            row["accepted_environment_revision"] == intent.accepted_environment_revision,
            row["expected_environment_revision"] + 1 == intent.accepted_environment_revision,
            row["data_revision"] == expected_data_revision,
            row["data_generation"] == expected_data_generation,
            row["command_request_digest"] == envelope.request_digest,
            row["authorization_decision_id"] == command.authorization_decision_id,
            command.status_code == 202 and result.outcome == "accepted",
            result.command_id == row["command_id"] == request.command_id,
            result.task_id == row["task_id"] and result.workspace_id == row["workspace_id"],
            result.environment_id == row["environment_id"] and result.operation_id == operation_id,
            result.action == row["action"] and result.request_digest == intent.request_digest,
            result.environment_revision == intent.accepted_environment_revision,
            result.version == client_request.expected_version + 1,
            result.control_revision == client_request.expected_control_revision,
            result.input_validity_revision == client_request.expected_input_validity_revision,
            envelope.request_schema_revision == "p1-workspace-development-" + row["action"] + "-r1",
            envelope.expected_resource_revision == client_request.expected_version,
            envelope.request_digest == row["command_request_digest"] == development_command_digest(
                envelope, client_request, workspace_id=row["workspace_id"],
                environment_id=None if row["action"] == "prepare" else row["environment_id"],
            ),
            intent.accepted_environment_revision == row["expected_environment_revision"] + 1,
            scope_ok,
            event["command_id"] == result.command_id and event["project_id"] == row["project_id"],
            event["aggregate_kind"] == "workspace_development_environment"
            and event["aggregate_id"] == row["environment_id"],
            event["aggregate_version"] == intent.accepted_environment_revision,
            event["event_type"] == DEVELOPMENT_OPERATION_EVENT
            and event["schema_version"] == DEVELOPMENT_OPERATION_SCHEMA,
            client_request.expected_workspace_revision == binding.workspace_revision,
            client_request.expected_write_generation == binding.write_generation,
            type(request) is PrepareWorkspaceDevelopmentEnvironment
            or client_request.expected_environment_revision == request.expected_environment_revision,
            type(request) is PrepareWorkspaceDevelopmentEnvironment
            or client_request.expected_data_revision == request.expected_data_revision,
            type(request) is PrepareWorkspaceDevelopmentEnvironment
            or client_request.expected_data_generation == request.expected_data_generation,
            type(request) is not ResetWorkspaceDevelopmentData
            or client_request.target_data_revision == request.target_data_revision,
        )):
            raise ValueError
        if type(request) is PrepareWorkspaceDevelopmentEnvironment:
            spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(request.spec.model_dump(mode="python"))
            if (spec.environment_id != row["environment_id"] or spec.binding != binding
                    or spec.storage_ref.model_dump(mode="json") != row["storage_ref_json"]
                    or spec.toolchain.model_dump(mode="json") != row["toolchain_json"]
                    or spec.original_lock_digest != row["original_lock_digest"]
                    or spec.dependency_cache_key != row["dependency_cache_key"]
                    or spec.migration_revision != row["migration_revision"]):
                raise ValueError
        elif request.source_manifest_digest != row["source_manifest_digest"]:
            raise ValueError
        return intent, client_request, row, result, event["created_at"]
    except (ValueError, TypeError, KeyError, AttributeError):
        raise WorkspaceDevelopmentError("workspace_development_operation_invalid") from None


def read_development_operation(uow: UnitOfWork, operation_id: str, *, reconciliation=False):
    """Recheck live authority and Workspace binding before any new Runner effect."""
    require_transaction(uow.connection)
    intent, client_request, row, _, _ = read_development_operation_record(uow.connection, operation_id)
    actor = actor_for_command(uow, row["command_id"])
    task, authorization = lock_task_access(uow, actor, row["task_id"], DEVELOPMENT_OPERATION_ACTION)
    authorize_current(uow, actor, AuthoritativeResource(
        row["project_id"], "operation", operation_id, task_id=row["task_id"],
    ), "operation.query")
    workspace = read_workspace_row(uow.connection, row["workspace_id"], for_update=True)
    environment = read_development_environment(uow.connection, row["environment_id"], for_update=True)
    if (task["project_id"] != row["project_id"] or environment["task_id"] != row["task_id"]
            or environment["workspace_id"] != row["workspace_id"] or workspace["task_id"] != row["task_id"]):
        raise WorkspaceDevelopmentError("workspace_development_scope_mismatch")
    if row["operation_state"] not in {"pending", "unknown"} and not reconciliation:
        raise WorkspaceDevelopmentError("workspace_development_operation_not_pending")
    if environment["environment_revision"] != intent.accepted_environment_revision and not reconciliation:
        raise WorkspaceDevelopmentError("workspace_development_revision_stale")
    if not reconciliation:
        cleanup = client_request.action in {"suspend", "dispose"}
        if not cleanup:
            task = require_ordinary_progress(
                uow.connection, row["task_id"], expected_version=task["version"],
                expected_control_revision=client_request.expected_control_revision,
                expected_input_validity_revision=client_request.expected_input_validity_revision,
                allowed_states=("draft", "active"),
            )
            current_engineering_input(uow.connection, task, client_request.input_set_ref)
        current_binding = WorkspaceBinding.model_validate(workspace["binding_json"])
        cleanup = client_request.action in {"suspend", "dispose"}
        if client_request.action in {"prepare", "resume", "reset_data"} and current_binding != intent.request.binding:
            raise WorkspaceDevelopmentError("workspace_development_binding_stale")
        if not cleanup and (current_binding.workspace_revision != client_request.expected_workspace_revision
                or current_binding.write_generation != client_request.expected_write_generation):
            raise WorkspaceDevelopmentError("workspace_development_workspace_generation_stale")
    return DevelopmentOperationAccess(
        intent=intent, client_request=client_request, task=task, workspace=workspace,
        environment=environment, authorization=authorization, reconciliation_only=reconciliation,
    )


def pending_development_operations(connection: Connection, task_id: str):
    """Project unsettled, real development intents into the Task completion barrier."""
    require_transaction(connection)
    rows = connection.execute(select(operation_table.c.operation_id).where(
        operation_table.c.task_id == task_id,
        operation_table.c.operation_state.in_(("pending", "unknown")),
    ).order_by(operation_table.c.operation_id).limit(129)).all()
    if len(rows) > 128:
        raise WorkspaceDevelopmentError("workspace_development_operation_scope_too_large")
    pending = []
    for (operation_id,) in rows:
        intent, _, row, _, _ = read_development_operation_record(connection, operation_id)
        reference = EngineeringRef(
            kind="operation", object_id=operation_id, revision=DEVELOPMENT_OPERATION_SCHEMA,
            authority="workspaces", digest=intent.request_digest, digest_algorithm="sha256",
        )
        pending.append(OperationClosureFact(
            operation_ref=reference, owner_kind="task", owner_id=task_id,
            affects_completion=True, closure="unknown",
        ))
    return tuple(pending)


def query_development_environment_in_uow(uow, actor, environment_id):
    initial = read_development_environment(uow.connection, environment_id)
    task, _ = lock_task_access(uow, actor, initial["task_id"], "resource.read")
    row = read_development_environment(uow.connection, environment_id, for_update=True)
    if row["task_id"] != task["task_id"] or row["project_id"] != task["project_id"]:
        raise WorkspaceDevelopmentError("workspace_development_environment_not_found", status_code=404)
    latest = uow.connection.execute(select(operation_table).where(
        operation_table.c.environment_id == environment_id,
        operation_table.c.observation_json.is_not(None),
    ).order_by(operation_table.c.accepted_environment_revision.desc()).limit(1)).mappings().one_or_none()
    observation = None if latest is None else WorkspaceDevelopmentEnvironmentObservation.model_validate(
        latest["observation_json"],
    )
    pending = uow.connection.execute(select(operation_table.c.operation_id).where(
        operation_table.c.environment_id == environment_id,
        operation_table.c.operation_state.in_(("pending", "unknown")),
    ).order_by(operation_table.c.accepted_environment_revision).limit(129)).scalars().all()
    if len(pending) > 128:
        raise WorkspaceDevelopmentError("workspace_development_operation_scope_too_large")
    return WorkspaceDevelopmentEnvironmentView(
        environment_id=environment_id, workspace_id=row["workspace_id"],
        binding=WorkspaceBinding.model_validate(row["binding_json"]),
        environment_revision=row["environment_revision"], state=row["state"],
        pending_operation_ids=tuple(pending), latest_observation=observation,
    )


def query_development_operation_in_uow(uow, actor, environment_id, operation_id):
    require_transaction(uow.connection)
    target = uow.connection.execute(select(operation_table).where(
        operation_table.c.operation_id == operation_id,
    )).mappings().one_or_none()
    if target is None or target["environment_id"] != environment_id:
        raise WorkspaceDevelopmentError("workspace_development_operation_not_found", status_code=404)
    task, _ = lock_task_access(uow, actor, target["task_id"], "resource.read")
    authorize_current(uow, actor, AuthoritativeResource(
        target["project_id"], "operation", operation_id, task_id=target["task_id"],
    ), "operation.query")
    if target["task_id"] != task["task_id"]:
        raise WorkspaceDevelopmentError("workspace_development_operation_not_found", status_code=404)
    intent, _, row, result, accepted_at = read_development_operation_record(uow.connection, operation_id)
    observation = None if row["observation_json"] is None else WorkspaceDevelopmentEnvironmentObservation.model_validate(
        row["observation_json"],
    )
    return WorkspaceDevelopmentOperationView(
        result=result, accepted_environment_revision=intent.accepted_environment_revision,
        operation_state=row["operation_state"], accepted_at=accepted_at, closed_at=row["closed_at"],
        observation=observation,
    )
