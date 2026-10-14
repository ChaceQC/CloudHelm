"""Versioned invalidation and Task links to already registered execution intents."""

from sqlalchemy import insert, select

from modules.collaboration.command_support import command_result, record_event, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import check_task_revisions, require_ordinary_progress
from modules.collaboration.records import read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs, task_operation_links
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from packages.contracts.p1.task_facts import OperationIntentMetadata, operation_scope_digest


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
