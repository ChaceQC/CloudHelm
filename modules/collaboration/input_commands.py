"""Versioned invalidation and Task links to already registered execution intents."""

from sqlalchemy import insert, select

from database.commands import CommandConflict
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.command_support import (
    assert_result_read_access, command_result, persist_result, prepare_task_command,
    record_event, rejected_result, update_task,
)
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import check_task_revisions, read_task, require_ordinary_progress
from modules.collaboration.initial_inputs import validate_initial_input_set
from modules.collaboration.records import read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs, task_operation_links
from modules.identity.actors import Actor, AuthoritativeResource, validate_actor
from modules.identity.authorization import authorize_current
from packages.contracts.p1.task_facts import OperationIntentMetadata, operation_scope_digest
from packages.contracts.p1.task_internal import BindInitialTaskInputRequest
from packages.contracts.p1.task_results import TaskCommandResult, TaskHttpResult


def bind_initial_input(context, request: BindInitialTaskInputRequest):
    context.task = require_ordinary_progress(
        context.uow.connection, context.task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision,
        allowed_states=("draft", "active"),
    )
    task = context.task
    existing = context.uow.connection.scalar(select(task_inputs.c.input_set_key).where(
        task_inputs.c.task_id == task["task_id"],
    ).limit(1))
    if task["input_validity_revision"] != 0 or existing is not None:
        raise TaskBoundaryError("task_initial_input_already_bound")
    input_record, source_record = validate_initial_input_set(
        context.uow.connection, task, request.input_set_ref,
    )
    update_task(context, input_validity_revision=1)
    context.uow.connection.execute(insert(task_inputs).values(
        task_id=task["task_id"], input_validity_revision=1,
        input_set_key=reference_key(task["project_id"], input_record.reference),
        source_key=reference_key(task["project_id"], source_record.reference),
    ))
    result = command_result(context, "input_bound", "task_initial_input_bound")
    record_event(context, result, "task.initial_input_bound", change_ref=input_record.reference)
    return result, 200


def bind_initial_input_in_uow(
    uow: UnitOfWork, actor: Actor, task_id: str, request: BindInitialTaskInputRequest,
    *, idempotency_key: str,
) -> TaskHttpResult:
    """Use the caller's transaction; task.command never replaces workspace.write.

    Fresh authorization precedes replay. Only a new command enters transition gates;
    command, input binding, Task version and event roll back with the caller's UoW.
    """
    require_transaction(uow.connection)
    if type(request) is not BindInitialTaskInputRequest:
        raise TaskBoundaryError("task_request_schema_invalid", status_code=422)
    try:
        request = BindInitialTaskInputRequest.model_validate(request.model_dump(mode="python"))
    except ValueError:
        raise TaskBoundaryError("task_request_schema_invalid", status_code=422) from None
    validate_actor(actor)
    try:
        context, existing = prepare_task_command(uow, actor, task_id, request, idempotency_key)
        if existing is not None:
            result = TaskCommandResult.model_validate(existing.result)
            assert_result_read_access(context, result)
            return TaskHttpResult(status_code=existing.status_code, body=result)
        try:
            with uow.connection.begin_nested():
                result, status = bind_initial_input(context, request)
        except TaskBoundaryError as error:
            context.task = read_task(uow.connection, task_id, for_update=True)
            result, status = rejected_result(context, error)
        return persist_result(context, result, status)
    except CommandConflict as error:
        raise TaskBoundaryError(str(error)) from None


def _advance_input_validity(context, **values) -> None:
    task = context.task
    previous = context.uow.connection.execute(select(task_inputs).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).mappings().one_or_none()
    revision = task["input_validity_revision"] + 1
    update_task(context, input_validity_revision=revision, input_status="needs_review", **values)
    if previous is not None:
        copied = dict(previous)
        copied["input_validity_revision"] = revision
        context.uow.connection.execute(insert(task_inputs).values(**copied))


def invalidate_input(context, request):
    read_registered_reference(context.uow.connection, context.task["project_id"], request.change_ref)
    if context.task["state"] in {"completed", "cancelled"}:
        result = command_result(context, "impact_archived", "followup_task_required")
        record_event(context, result, "task.closed_input_impact", change_ref=request.change_ref, reason=request.reason)
        return result, 200
    check_task_revisions(context.task, expected_version=request.expected_version,
                         expected_control_revision=request.expected_control_revision,
                         expected_input_validity_revision=request.expected_input_validity_revision)
    _advance_input_validity(context)
    result = command_result(context, "input_invalidated", "task_input_needs_review")
    record_event(context, result, "task.input_invalidated", change_ref=request.change_ref, reason=request.reason)
    return result, 200


def _execution_intent(context, operation_ref):
    record = read_registered_reference(context.uow.connection, context.task["project_id"], operation_ref)
    intent = record.metadata
    if not isinstance(intent, OperationIntentMetadata):
        raise TaskBoundaryError("registered_operation_intent_required")
    if intent.owner_kind == "task" and intent.owner_id != context.task["task_id"]:
        raise TaskBoundaryError("operation_owner_mismatch")
    owner_task = intent.owner_id if intent.owner_kind == "task" else None
    resource = AuthoritativeResource(context.task["project_id"], "operation", operation_ref.object_id,
                                     task_id=owner_task)
    authorize_current(context.uow, context.actor, resource, "operation.query")
    input_row = context.uow.connection.execute(select(task_inputs).where(
        task_inputs.c.task_id == context.task["task_id"],
        task_inputs.c.input_validity_revision == context.task["input_validity_revision"],
    )).mappings().one_or_none()
    key = reference_key(context.task["project_id"], intent.input_set_ref)
    if input_row is None or input_row["input_set_key"] != key:
        raise TaskBoundaryError("operation_input_not_current")
    read_registered_reference(context.uow.connection, context.task["project_id"], intent.input_set_ref)
    return intent, key


def register_write_intent(context, request):
    context.task = require_ordinary_progress(
        context.uow.connection, context.task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision,
    )
    intent, input_key = _execution_intent(context, request.operation_ref)
    scope_digest = operation_scope_digest(request.operation_ref, intent.attempt_id, intent.step_ids,
                                         intent.executor_id, intent.executor_generation, intent.input_set_ref)
    existing = context.uow.connection.execute(select(task_operation_links).where(
        task_operation_links.c.task_id == context.task["task_id"],
        task_operation_links.c.operation_id == request.operation_ref.object_id,
    )).mappings().one_or_none()
    if existing is not None:
        if existing["operation_ref"] != request.operation_ref.model_dump(mode="json") or existing["effect_scope_digest"] != scope_digest:
            raise TaskBoundaryError("operation_identity_conflict")
        return command_result(context, "write_intent_registered", "existing_task_write_intent",
                              operation_id=request.operation_ref.object_id), 200
    # Admission changes the intent set, not the source bytes. Unknown writes
    # already block completion; actual input changes use invalidate_input.
    update_task(context, operation_set_revision=context.task["operation_set_revision"] + 1)
    context.uow.connection.execute(insert(task_operation_links).values(
        task_id=context.task["task_id"], operation_id=request.operation_ref.object_id,
        operation_ref=request.operation_ref.model_dump(mode="json"), owner_kind=intent.owner_kind,
        owner_id=intent.owner_id, affects_completion=True, attempt_id=intent.attempt_id,
        executor_id=intent.executor_id, executor_generation=intent.executor_generation,
        input_set_key=input_key, effect_scope_digest=scope_digest,
        admitted_control_revision=context.task["control_revision"],
    ))
    result = command_result(context, "write_intent_registered", "task_write_intent_registered",
                            operation_id=request.operation_ref.object_id)
    record_event(context, result, "task.write_intent_registered", operation_ref=request.operation_ref)
    return result, 200
