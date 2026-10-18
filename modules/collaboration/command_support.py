"""Shared mechanics inside the Task application; no independent transaction owner."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import MAX_REVISION, read_task, task_resource
from modules.collaboration.tables import task_operation_links, tasks
from modules.identity.actors import Actor, AuthoritativeResource, AuthorizationDecision
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.identity.locking import lock_current_subject, lock_project_policy
from modules.sync.events import append_event
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p0.task_control_contracts import TaskControlRequest
from packages.contracts.p1.task_internal import (
    BindInitialTaskInputRequest, InvalidateTaskInputRequest, RegisterTaskWriteIntentRequest,
    TaskAdvanceRequest, TaskChangedEvent,
)
from packages.contracts.p1.task_requests import (
    CancelTaskRequest, CompleteTaskRequest, ReconcileTaskRequest, StartTaskRequest,
)
from packages.contracts.p1.task_results import TaskBlocker, TaskCommandResult, TaskHttpResult


@dataclass
class TaskAccessContext:
    uow: UnitOfWork
    actor: Actor
    task: Mapping[str, Any]
    authorization: AuthorizationDecision


@dataclass
class TaskCommandContext(TaskAccessContext):
    envelope: CommandEnvelope


def request_action(request: Contract) -> str:
    if isinstance(request, CancelTaskRequest):
        return "task.cancel"
    if isinstance(request, (ReconcileTaskRequest, TaskAdvanceRequest)) and request.purpose == "cancellation":
        return "task.cancel"
    return "fact.archive" if isinstance(request, InvalidateTaskInputRequest) else "task.command"


def normalized_request(request: Contract) -> tuple[str, Contract]:
    if isinstance(request, CompleteTaskRequest):
        return "p0-task-control-r1", TaskControlRequest(
            action="complete_task", expected_control_revision=request.expected_control_revision,
            expected_input_validity_revision=request.expected_input_validity_revision,
        )
    if isinstance(request, CancelTaskRequest):
        return "p0-task-control-r1", TaskControlRequest(
            action="cancel_task", expected_control_revision=request.expected_control_revision,
            cancel_reason=request.cancel_reason,
        )
    schemas = {
        StartTaskRequest: "p1-task-start-r1", ReconcileTaskRequest: "p1-task-reconcile-r1",
        BindInitialTaskInputRequest: "p1-task-initial-input-bind-r1",
        InvalidateTaskInputRequest: "p1-task-input-invalidate-r1",
        RegisterTaskWriteIntentRequest: "p1-task-write-intent-r1", TaskAdvanceRequest: "p1-task-advance-r1",
    }
    if type(request) not in schemas:
        raise TaskBoundaryError("task_request_schema_invalid", status_code=422)
    return schemas[type(request)], request


def lock_task_access(uow: UnitOfWork, actor: Actor, task_id: str, action: str):
    project_id = read_task(uow.connection, task_id)["project_id"]
    lock_current_subject(uow, actor)
    lock_project_policy(uow, project_id)
    task = read_task(uow.connection, task_id, for_update=True)
    if task["project_id"] != project_id:
        raise TaskBoundaryError("task_ownership_changed")
    resource = task_resource(task)
    authorization = authorize_current(uow, actor, resource, action)
    if action != "resource.read":
        authorize_current(uow, actor, resource, "resource.read")
    return task, authorization


def prepare_task_command(uow: UnitOfWork, actor: Actor, task_id: str, request: Contract, key: str):
    action = request_action(request)
    task, authorization = lock_task_access(uow, actor, task_id, action)
    schema, body = normalized_request(request)
    resource = task_resource(task)
    intent = CommandIntent(request_schema_revision=schema, caller=actor.principal,
                           scope=resource.scope, target=resource.target_scope, action=action,
                           expected_resource_revision=request.expected_version)
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                               idempotency_key=key, request_digest=request_digest(intent, body))
    context = TaskCommandContext(uow, actor, task, authorization, envelope)
    return context, lock_and_get(uow.connection, envelope)


def update_task(context: TaskCommandContext, **values) -> None:
    task = context.task
    assert_schema_ready(context.uow.connection)
    if task["version"] == MAX_REVISION:
        raise TaskBoundaryError("revision_exhausted")
    if any(values.get(name, 0) > MAX_REVISION for name in ("control_revision", "input_validity_revision", "operation_set_revision")):
        raise TaskBoundaryError("revision_exhausted")
    row = context.uow.connection.execute(update(tasks).where(
        tasks.c.task_id == task["task_id"], tasks.c.version == task["version"],
        tasks.c.control_revision == task["control_revision"],
        tasks.c.input_validity_revision == task["input_validity_revision"],
        tasks.c.operation_set_revision == task["operation_set_revision"],
    ).values(version=task["version"] + 1, **values).returning(*tasks.c)).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("resource_revision_conflict")
    context.task = row


def command_result(context: TaskCommandContext, outcome: str, code: str, **fields) -> TaskCommandResult:
    task = context.task
    return TaskCommandResult(
        command_id=context.envelope.command_id, task_id=task["task_id"], outcome=outcome, code=code,
        state=task["state"], version=task["version"], control_revision=task["control_revision"],
        input_validity_revision=task["input_validity_revision"],
        completion_report_id=task["completion_report_id"], **fields,
    )


def _read_operation_access(context: TaskAccessContext, operation_id: str) -> None:
    link = context.uow.connection.execute(select(task_operation_links).where(
        task_operation_links.c.task_id == context.task["task_id"],
        task_operation_links.c.operation_id == operation_id,
    )).mappings().one_or_none()
    if link is None:
        owner_task = _engineering_operation_owner(context, operation_id)
    else:
        owner_task = link["owner_id"] if link["owner_kind"] == "task" else None
    resource = AuthoritativeResource(context.task["project_id"], "operation", operation_id,
                                     task_id=owner_task)
    authorize_current(context.uow, context.actor, resource, "operation.query")


def _engineering_operation_owner(context: TaskAccessContext, operation_id: str) -> str:
    """Resolve a validated domain intent before exposing its ID in Task blockers."""
    from modules.delivery.queries import read_build_intent
    from modules.workspaces.operations import read_workspace_operation

    try:
        if operation_id.startswith("workspace-dev-env-"):
            from modules.workspaces.development_queries import read_development_operation_record

            _, _, row, _, _ = read_development_operation_record(context.uow.connection, operation_id)
            project_id, task_id = row["project_id"], row["task_id"]
        elif operation_id.startswith("workspace-"):
            intent, _ = read_workspace_operation(context.uow.connection, operation_id)
            project_id, task_id = intent.result.binding.project_id, intent.result.task_id
        elif operation_id.startswith("build-operation-"):
            _, intent = read_build_intent(context.uow.connection, operation_id)
            project_id, task_id = intent.project_id, intent.task_id
        else:
            raise IdentityError("permission_denied")
    except TaskBoundaryError:
        raise IdentityError("permission_denied") from None
    if (project_id, task_id) != (context.task["project_id"], context.task["task_id"]):
        raise IdentityError("permission_denied")
    return task_id


def assert_result_read_access(context: TaskAccessContext, result: TaskCommandResult) -> None:
    identities = {blocker.object_id for blocker in result.blockers if blocker.object_kind == "operation"}
    if result.operation_id is not None:
        identities.add(result.operation_id)
    for identity in sorted(identities - {None}):
        _read_operation_access(context, identity)


def visible_blockers(context: TaskAccessContext, blockers: tuple[TaskBlocker, ...]) -> tuple[TaskBlocker, ...]:
    visible = []
    for blocker in blockers:
        if blocker.object_kind == "operation" and blocker.object_id is not None:
            try:
                _read_operation_access(context, blocker.object_id)
            except IdentityError:
                blocker = TaskBlocker(code=blocker.code, object_id=context.task["task_id"])
        if blocker not in visible:
            visible.append(blocker)
    return tuple(visible)


def rejected_result(context: TaskCommandContext, error: TaskBoundaryError):
    # Detailed cross-object blockers use visible_blockers explicitly. A generic
    # failure must not echo an unreviewed producer object's identity.
    blockers = (TaskBlocker(code=error.code, object_id=context.task["task_id"]),) if error.object_ids else ()
    return command_result(context, "blocked" if blockers else "rejected", error.code,
                          blockers=blockers), error.status_code


def record_event(context: TaskCommandContext, result: TaskCommandResult, event_type: str, **references) -> None:
    append_event(context.uow.connection, command_id=context.envelope.command_id,
                 project_id=context.task["project_id"], aggregate_kind="task",
                 aggregate_id=context.task["task_id"], aggregate_version=context.task["version"],
                 event_type=event_type, schema_version="p1-task-event-r1",
                 payload=TaskChangedEvent(result=result, **references))


def persist_result(context: TaskCommandContext, result: TaskCommandResult, status_code: int) -> TaskHttpResult:
    save_result(context.uow.connection, context.envelope, result, status_code=status_code,
                authorization=context.authorization.envelope)
    return TaskHttpResult(status_code=status_code, body=result)
