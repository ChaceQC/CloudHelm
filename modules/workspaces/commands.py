"""Workspace command acceptance inside a caller-owned short transaction."""

from uuid import uuid4

from sqlalchemy import insert, select, update

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import require_transaction
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import MAX_REVISION, read_task, require_ordinary_progress, task_resource
from modules.collaboration.tables import work_items
from modules.sync.events import append_event
from modules.workspaces.operations import (
    OPERATION_SCHEMA, REQUEST_SCHEMAS, WorkspaceError, WorkspaceOperationIntent, current_engineering_input,
    operation_identity, operation_request_digest, pending_workspace_operations, read_workspace_row,
)
from modules.workspaces.tables import workspaces
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p1.workspace_records import workspace_metadata_digest
from packages.contracts.p1.workspace_requests import (
    WorkspaceCommandResult, WorkspaceHttpResult, WorkspaceRequest,
)


def _prepare(uow, actor, task_id, workspace_id, request, key):
    action = "candidate.submit" if request.kind == "candidate" else "workspace.write"
    task, authorization = lock_task_access(uow, actor, task_id, action)
    workspace = None if workspace_id is None else read_workspace_row(uow.connection, workspace_id, for_update=True)
    if workspace is not None and workspace["task_id"] != task_id:
        raise WorkspaceError("workspace_not_found", status_code=404)
    resource = task_resource(task)
    intent = CommandIntent(
        request_schema_revision=REQUEST_SCHEMAS[request.kind], caller=actor.principal,
        scope=resource.scope, target=resource.target_scope, action=action,
        expected_resource_revision=request.expected_version,
    )
    # A workspace target is part of the digest even though the stable authorization
    # scope remains the Task for recorded/delegated worker identities.
    body = _ScopedRequest(workspace_id=workspace_id, request=request)
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
                               request_digest=request_digest(intent, body))
    return TaskCommandContext(uow, actor, task, authorization, envelope), workspace, lock_and_get(uow.connection, envelope)


class _ScopedRequest(Contract):
    workspace_id: Identifier | None
    request: WorkspaceRequest


def workspace_command_digest(envelope, request, workspace_id):
    return request_digest(envelope, _ScopedRequest(workspace_id=workspace_id, request=request))


def _result(context, request, outcome, code, **values):
    task = context.task
    return WorkspaceCommandResult(
        command_id=context.envelope.command_id, task_id=task["task_id"], kind=request.kind,
        outcome=outcome, code=code, version=task["version"], control_revision=task["control_revision"],
        input_validity_revision=task["input_validity_revision"], input_set_ref=request.input_set_ref, **values,
    )


def _guard(context, request, workspace):
    context.task = require_ordinary_progress(
        context.uow.connection, context.task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision, allowed_states=("draft", "active"),
    )
    registration = current_engineering_input(context.uow.connection, context.task, request.input_set_ref)
    if workspace is None:
        return registration
    binding = WorkspaceBinding.model_validate(workspace["binding_json"])
    from modules.workspaces.handoff_gates import require_workspace_writer

    require_workspace_writer(context.uow.connection, workspace, context.actor, request.kind)
    if binding.workspace_revision != request.expected_workspace_revision:
        raise WorkspaceError("workspace_revision_conflict")
    if binding.write_generation != request.expected_write_generation:
        raise WorkspaceError("workspace_write_generation_conflict")
    source = registration.source_record.source
    if (source.source_id != binding.source_id or source.source_revision != binding.source_revision
            or registration.source_ref.revision != binding.base_commit):
        raise WorkspaceError("workspace_source_input_mismatch")
    pending = pending_workspace_operations(context.uow.connection, context.task["task_id"])
    if any(value.operation_ref.object_id.startswith("workspace-") and _belongs_to_workspace(
        context.uow.connection, value.operation_ref.object_id, binding.workspace_id,
    ) for value in pending):
        raise WorkspaceError("workspace_operation_pending")
    if request.kind == "materialize" and workspace["files_json"] is not None:
        raise WorkspaceError("workspace_already_materialized")
    if request.kind != "materialize" and workspace["files_json"] is None:
        raise WorkspaceError("workspace_not_materialized")
    item = context.uow.connection.execute(select(work_items).where(
        work_items.c.work_item_id == binding.work_item_id, work_items.c.task_id == context.task["task_id"],
    ).with_for_update()).mappings().one()
    if item["state"] not in {"ready", "running", "submitted"}:
        raise WorkspaceError("workspace_work_item_closed")
    if max(item["revision"], binding.workspace_revision, binding.write_generation) == MAX_REVISION:
        raise WorkspaceError("revision_exhausted")
    return registration


def _belongs_to_workspace(connection, operation_id, workspace_id):
    from modules.workspaces.operations import read_workspace_operation

    intent, _ = read_workspace_operation(connection, operation_id)
    return intent.result.workspace_id == workspace_id


def _create(context, request, registration, *, work_item=None):
    task, command = context.task, context.envelope
    source = registration.source_record.source
    binding = WorkspaceBinding(
        workspace_id="workspace-" + command.command_id, project_id=task["project_id"], task_id=task["task_id"],
        work_item_id=work_item["work_item_id"] if work_item is not None else "work-item-" + command.command_id,
        owner_user_id=context.actor.principal.delegator_id or context.actor.principal.subject_id,
        source_id=source.source_id, source_revision=source.source_revision,
        base_commit=registration.source_ref.revision, workspace_revision=1, write_generation=1,
    )
    goal = request.goal or read_declaration(context.uow.connection, task).goal
    if work_item is None:
        context.uow.connection.execute(insert(work_items).values(
            work_item_id=binding.work_item_id, task_id=task["task_id"], declaration_id=task["declaration_id"],
            revision=1, state="ready", required=True, goal=goal,
        ))
    context.uow.connection.execute(insert(workspaces).values(
        **binding.model_dump(), binding_json=binding.model_dump(mode="json"),
        binding_digest=workspace_metadata_digest(binding), created_by_command_id=command.command_id,
        authorization_decision_id=context.authorization.envelope.decision_id,
    ))
    update_task(context)
    result = _result(context, request, "created", "workspace_created", workspace_id=binding.workspace_id, binding=binding)
    append_event(context.uow.connection, command_id=command.command_id, project_id=task["project_id"],
                 aggregate_kind="workspace", aggregate_id=binding.workspace_id, aggregate_version=1,
                 event_type="workspace.created", schema_version="p1-workspace-created-event-r1", payload=result)
    return result, 201


def _accept(context, request, workspace, runtime_scope_for, has_enqueue):
    binding = WorkspaceBinding.model_validate(workspace["binding_json"])
    operation_id = operation_identity(request.kind, context.envelope.command_id)
    runtime_scope = None
    if request.kind == "candidate":
        if runtime_scope_for is None:
            raise WorkspaceError("workspace_runtime_scope_unavailable")
        runtime_scope = runtime_scope_for(binding)
        if not isinstance(runtime_scope, str):
            raise WorkspaceError("workspace_runtime_scope_unavailable")
    update_task(context, operation_set_revision=context.task["operation_set_revision"] + 1)
    # This item remains unaccepted; physical capture never supplies acceptance.
    context.uow.connection.execute(update(work_items).where(
        work_items.c.work_item_id == binding.work_item_id,
    ).values(revision=work_items.c.revision + 1, state="running"))
    provisional = _result(
        context, request, "accepted", "workspace_operation_queued" if has_enqueue else "workspace_awaiting_executor",
        workspace_id=binding.workspace_id, binding=binding, operation_id=operation_id,
        request_digest="sha256:" + "0" * 64,
    )
    value = WorkspaceOperationIntent(
        request=request, result=provisional, materialization_operation_id=workspace["materialization_operation_id"],
        runtime_scope_id=runtime_scope,
    )
    result = provisional.model_copy(update={"request_digest": operation_request_digest(value)})
    value = WorkspaceOperationIntent.model_validate({**value.model_dump(mode="python"), "result": result})
    append_event(context.uow.connection, command_id=context.envelope.command_id, project_id=binding.project_id,
                 aggregate_kind="workspace", aggregate_id=binding.workspace_id,
                 aggregate_version=binding.workspace_revision, event_type="workspace.operation_accepted",
                 schema_version=OPERATION_SCHEMA, event_id="workspace-intent-" + result.command_id, payload=value)
    return result, 202


def _accept_workspace_command(
    uow, actor, task_id, request: WorkspaceRequest, *, idempotency_key, workspace_id=None,
    runtime_scope_for=None, enqueue_operation=None,
):
    """Current authority precedes replay; all new intent/enqueue writes share this UoW."""
    require_transaction(uow.connection)
    if (request.kind == "create") != (workspace_id is None):
        raise WorkspaceError("workspace_request_target_invalid", status_code=422)
    context, workspace, existing = _prepare(uow, actor, task_id, workspace_id, request, idempotency_key)
    if existing is not None:
        result = WorkspaceCommandResult.model_validate(existing.result)
        if result.workspace_id is not None and workspace_id is not None and result.workspace_id != workspace_id:
            raise WorkspaceError("workspace_result_scope_mismatch")
        return WorkspaceHttpResult(status_code=existing.status_code, body=result)
    try:
        with uow.connection.begin_nested():
            assert_schema_ready(uow.connection)
            registration = _guard(context, request, workspace)
            result, status = (_create(context, request, registration) if workspace is None else
                              _accept(context, request, workspace, runtime_scope_for, enqueue_operation is not None))
    except TaskBoundaryError as error:
        context.task = read_task(uow.connection, task_id, for_update=True)
        result = _result(context, request, "rejected", error.code, workspace_id=workspace_id)
        status = 422 if error.status_code == 422 else 409
    save_result(uow.connection, context.envelope, result, status_code=status,
                authorization=context.authorization.envelope)
    if result.outcome == "accepted" and enqueue_operation is not None:
        enqueue_operation(uow, result.operation_id, result.command_id, result.workspace_id,
                          result.version, result.request_digest)
    return WorkspaceHttpResult(status_code=status, body=result)


def accept_workspace_command_in_uow(
    uow, actor, task_id, request: WorkspaceRequest, *, idempotency_key, workspace_id=None,
    runtime_scope_for=None, enqueue_operation=None,
):
    """Keep failed enqueue atomic even when the UoW owner catches its exception."""
    require_transaction(uow.connection)
    with uow.connection.begin_nested():
        return _accept_workspace_command(
            uow, actor, task_id, request, idempotency_key=idempotency_key, workspace_id=workspace_id,
            runtime_scope_for=runtime_scope_for, enqueue_operation=enqueue_operation,
        )
