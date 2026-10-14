"""Idempotent domain commands invoked from the two bounded DBOS steps."""

import hashlib

from sqlalchemy import select

from database.commands import get_by_id, lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import (
    TaskCommandContext, assert_result_read_access, lock_task_access,
    normalized_request, rejected_result,
)
from modules.collaboration.control_commands import advance_control
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import read_task, task_resource
from modules.collaboration.lifecycle_commands import advance_initial
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, CONTROL_WORKFLOW, INITIAL_WORKFLOW, queue_for
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.task_internal import TaskAdvanceRequest, TaskWorkflowRecord
from packages.contracts.p1.task_results import TaskCommandResult


def _source(uow, command_id, workflow_name):
    command = get_by_id(uow.connection, command_id)
    if command is None or command.status_code != 202:
        raise TaskBoundaryError("workflow_source_not_accepted")
    try:
        result = TaskCommandResult.model_validate(command.result)
    except ValueError:
        raise TaskBoundaryError("workflow_source_invalid") from None
    binding = uow.connection.execute(select(workflow_bindings).where(
        workflow_bindings.c.command_id == command_id,
        workflow_bindings.c.workflow_name == workflow_name,
    )).mappings().one_or_none()
    if (binding is None or binding["workflow_id"] != result.workflow_id
            or binding["business_kind"] != "task" or binding["business_id"] != result.task_id
            or binding["process_type"] != workflow_name or binding["advance_revision"] != result.version
            or binding["request_digest"] != command.envelope.request_digest
            or binding["application_name"] != APPLICATION_NAME or binding["application_version"] != APPLICATION_VERSION
            or binding["queue_name"] != queue_for(workflow_name)
            or result.command_id != command_id or command.envelope.target.resource_id != result.task_id
            or command.envelope.target.resource_kind != "task"):
        raise TaskBoundaryError("workflow_binding_invalid")
    if workflow_name == INITIAL_WORKFLOW:
        valid = (command.envelope.request_schema_revision == "p1-task-start-r1" and result.outcome == "started"
                 and command.envelope.action == "task.command")
        purpose = "initial"
    else:
        pairs = {"p0-task-control-r1": "cancellation_requested", "p1-task-reconcile-r1": "reconciliation_requested"}
        valid = (pairs.get(command.envelope.request_schema_revision) == result.outcome
                 and result.control_purpose in {"completion", "cancellation"}
                 and command.envelope.action == ("task.cancel" if result.control_purpose == "cancellation" else "task.command")
                 and (command.envelope.request_schema_revision != "p0-task-control-r1" or result.control_purpose == "cancellation"))
        purpose = result.control_purpose
    if not valid:
        raise TaskBoundaryError("workflow_source_kind_invalid")
    return binding, result, purpose


def _context(uow, actor, binding, task_id, purpose):
    action = "task.cancel" if purpose == "cancellation" else "task.command"
    task, _ = lock_task_access(uow, actor, task_id, action)
    resource = AuthoritativeResource(task["project_id"], "workflow_binding", binding["workflow_id"],
                                     revision=task["version"], task_id=task_id, target=task_resource(task).scope)
    authorization = authorize_current(uow, actor, resource, action)
    return task, resource, authorization


def _restore_record(uow, context, stored, source_command_id, purpose):
    try:
        record = TaskWorkflowRecord.model_validate(stored.result)
    except ValueError:
        raise TaskBoundaryError("workflow_command_record_invalid") from None
    invocation, envelope = record.invocation, stored.envelope
    schema, body = normalized_request(invocation)
    grant = context.authorization.envelope
    if (invocation.source_command_id != source_command_id or invocation.purpose != purpose
            or record.result.command_id != envelope.command_id or record.result.task_id != context.task["task_id"]
            or record.status_code != stored.status_code or envelope.request_schema_revision != schema
            or envelope.request_digest != request_digest(envelope, body)
            or any(getattr(envelope, key) != getattr(grant, key) for key in ("caller", "scope", "target", "action"))):
        raise TaskBoundaryError("workflow_command_record_invalid")
    lock_and_get(uow.connection, envelope)
    assert_result_read_access(context, record.result)
    return record.result


def _new_invocation(source_command_id, original, task, purpose):
    if purpose == "initial":
        version, control, inputs = original.version, original.control_revision, original.input_validity_revision
    else:
        # A control request observes current state; old completion inputs cannot
        # indefinitely prevent cancellation. This first snapshot is persisted.
        version, control, inputs = task["version"], task["control_revision"], task["input_validity_revision"]
    return TaskAdvanceRequest(source_command_id=source_command_id, purpose=purpose,
                              expected_version=version, expected_control_revision=control,
                              expected_input_validity_revision=inputs)


def _apply_step(context, invocation):
    try:
        with context.uow.connection.begin_nested():
            if invocation.purpose == "initial":
                return advance_initial(context, invocation)
            return advance_control(context, invocation)
    except TaskBoundaryError as error:
        context.task = read_task(context.uow.connection, context.task["task_id"], for_update=True)
        return rejected_result(context, error)


def run_step(engine, source_command_id: str, workflow_name: str) -> TaskCommandResult:
    with UnitOfWork(engine) as uow:
        binding, original, purpose = _source(uow, source_command_id, workflow_name)
        actor = actor_for_command(uow, source_command_id)
        task, resource, authorization = _context(uow, actor, binding, original.task_id, purpose)
        identity = "task-step-" + hashlib.sha256((workflow_name + "\0" + source_command_id).encode("utf-8")).hexdigest()
        stored = get_by_id(uow.connection, identity)
        if stored is not None:
            context = TaskCommandContext(uow, actor, task, authorization, stored.envelope)
            return _restore_record(uow, context, stored, source_command_id, purpose)
        invocation = _new_invocation(source_command_id, original, task, purpose)
        schema, body = normalized_request(invocation)
        intent = CommandIntent(request_schema_revision=schema, caller=actor.principal,
                               scope=resource.scope, target=resource.target_scope, action=authorization.envelope.action,
                               expected_resource_revision=invocation.expected_version)
        envelope = CommandEnvelope(**intent.model_dump(), command_id=identity, idempotency_key="advance",
                                   request_digest=request_digest(intent, body))
        context = TaskCommandContext(uow, actor, task, authorization, envelope)
        existing = lock_and_get(uow.connection, envelope)
        if existing is not None:
            return _restore_record(uow, context, existing, source_command_id, purpose)
        result, status = _apply_step(context, invocation)
        record = TaskWorkflowRecord(invocation=invocation, result=result, status_code=status)
        save_result(uow.connection, envelope, record, status_code=status, authorization=authorization.envelope)
        return result
