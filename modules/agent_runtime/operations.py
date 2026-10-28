"""Original engineering operations and their durable, on-demand result waits."""

import hashlib
from datetime import UTC

import rfc8785
from pydantic_ai.exceptions import CallDeferred
from sqlalchemy import insert, select, update

from database.commands import commands, get_by_id
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import require_ordinary_progress
from modules.collaboration.records import reference_key
from modules.collaboration.tables import task_wait_conditions
from modules.identity.actors import actor_for_command
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.delivery.queries import build_view, read_build_intent
from modules.workflow.engineering_enqueuers import engineering_enqueuer
from modules.workspaces.commands import accept_workspace_command_in_uow
from modules.workspaces.development_queries import (
    query_development_operation_in_uow, read_development_operation_record,
)
from modules.workspaces.operations import read_workspace_operation, read_workspace_row
from modules.workspaces.queries import query_workspace_operation_in_uow
from packages.contracts.p0.core_contracts import AcceptedReceipt
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p1.workspace_requests import MaterializeWorkspaceRequest, WorkspaceCommandResult
from packages.contracts.p2.runtime import RuntimeStartRequest
from .admission import current_run
from .operation_tables import agent_operation_waits
from .registration import enqueue_wait_continuation_in_uow
from .tables import agent_runs, agent_sessions


def _argument(arguments, name):
    if (not isinstance(arguments, dict) or set(arguments) != {name}
            or not isinstance(arguments[name], str) or not 1 <= len(arguments[name]) <= 160):
        raise TaskBoundaryError("agent_operation_arguments_invalid", status_code=422)
    return arguments[name]


def _identity(run_id, tool_call_id):
    if not isinstance(tool_call_id, str) or not 1 <= len(tool_call_id) <= 160:
        raise TaskBoundaryError("agent_tool_call_identity_invalid", status_code=422)
    return hashlib.sha256(rfc8785.dumps([run_id, tool_call_id])).hexdigest()


def _receipt(result):
    if result.outcome != "accepted":
        return {"status": "rejected", "code": result.code}
    reference = EngineeringRef(kind="operation", object_id=result.operation_id,
        revision="p1-workspace-operation-r1", authority="workspaces",
        digest=result.request_digest, digest_algorithm="sha256")
    return AcceptedReceipt(operation_id=result.operation_id, request_digest=result.request_digest,
        query_ref=reference, wait_ref=reference).model_dump(mode="json")


def _result_in_uow(uow, source_command_id, request, operation_id):
    """Only the original principal's supported operation for this work item is exposed."""
    actor = actor_for_command(uow, source_command_id)
    if operation_id.startswith("build-operation-"):
        _, record = read_build_intent(uow.connection, operation_id)
        operation_actor = actor_for_command(uow, record.command_id)
        binding = record.fixed_inputs.candidate.binding
        if (record.task_id != request.runtime_input.task_id
                or binding.work_item_id != request.context.work_item_id
                or operation_actor.principal != actor.principal):
            raise TaskBoundaryError("agent_operation_not_found", status_code=404)
        lock_task_access(uow, actor, record.task_id, "resource.read")
        authorize_current(uow, actor, AuthoritativeResource(
            record.project_id, "operation", operation_id, task_id=record.task_id), "operation.query")
        view = build_view(uow.connection, record)
        if view.state not in {"succeeded", "failed"}:
            return None
        return {"operation_id": operation_id, "request_digest": record.request_digest,
                "state": "registered", "registration": view.model_dump(mode="json")}
    if operation_id.startswith("workspace-dev-env-"):
        intent, _, _, accepted, _ = read_development_operation_record(uow.connection, operation_id)
        operation_actor = actor_for_command(uow, accepted.command_id)
        if (accepted.task_id != request.runtime_input.task_id
                or intent.request.binding.work_item_id != request.context.work_item_id
                or operation_actor.principal != actor.principal):
            raise TaskBoundaryError("agent_operation_not_found", status_code=404)
        view = query_development_operation_in_uow(uow, actor, accepted.environment_id, operation_id)
        if view.operation_state not in {"succeeded", "failed"}:
            return None
        return {"operation_id": operation_id, "request_digest": accepted.request_digest,
                "state": "registered", "registration": {
                    "environment_id": accepted.environment_id, "state": view.operation_state,
                    "observation": view.observation.model_dump(mode="json")}}
    intent, _ = read_workspace_operation(uow.connection, operation_id)
    operation_actor = actor_for_command(uow, intent.result.command_id)
    if (intent.result.kind not in {"materialize", "mutate", "candidate"} or intent.result.task_id != request.runtime_input.task_id
            or intent.result.binding.work_item_id != request.context.work_item_id
            or operation_actor.principal != actor.principal):
        raise TaskBoundaryError("agent_operation_not_found", status_code=404)
    view = query_workspace_operation_in_uow(uow, actor, intent.result.workspace_id, operation_id)
    if view.registration is None:
        return None
    return {"operation_id": operation_id, "request_digest": intent.result.request_digest,
            "state": "registered", "registration": view.registration.model_dump(mode="json")}


def _digest(value):
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


class OperationGateway:
    def __init__(self, engine, client):
        self.engine, self.client = engine, client

    def submit_operation(self, run_id, tool_call_id, arguments):
        workspace_id = _argument(arguments, "workspace_id")
        key = "agent-tool-" + _identity(run_id, tool_call_id)
        with UnitOfWork(self.engine) as uow:
            task, _, run, request, _ = current_run(uow, run_id)
            actor = actor_for_command(uow, run["source_command_id"])
            task, _ = lock_task_access(uow, actor, task["task_id"], "workspace.write")
            workspace = read_workspace_row(uow.connection, workspace_id, for_update=True)
            binding = WorkspaceBinding.model_validate(workspace["binding_json"])
            if (binding.task_id != task["task_id"] or binding.work_item_id != request.context.work_item_id):
                raise TaskBoundaryError("agent_workspace_not_found", status_code=404)
            previous_id = uow.connection.scalar(select(commands.c.command_id).where(
                commands.c.idempotency_key.startswith(key), commands.c.project_id == task["project_id"],
                commands.c.resource_kind == "task", commands.c.resource_id == task["task_id"],
                commands.c.caller_kind == actor.principal.kind, commands.c.subject_id == actor.principal.subject_id,
                commands.c.delegator_id == actor.principal.delegator_id))
            if previous_id is not None:
                previous = get_by_id(uow.connection, previous_id)
                if previous.envelope.idempotency_key != key:
                    raise TaskBoundaryError("agent_tool_call_identity_conflict")
                result = WorkspaceCommandResult.model_validate(previous.result)
                if (previous.envelope.action != "workspace.write" or result.kind != "materialize"
                        or result.task_id != task["task_id"] or result.workspace_id != workspace_id):
                    raise TaskBoundaryError("agent_tool_call_identity_conflict")
                if result.outcome == "accepted":
                    read_workspace_operation(uow.connection, result.operation_id)
                return _receipt(result)
            value = MaterializeWorkspaceRequest(expected_version=task["version"],
                expected_control_revision=request.runtime_input.expected_task_control_revision,
                expected_input_validity_revision=request.runtime_input.expected_input_validity_revision,
                input_set_ref=request.context.input_set_ref, expected_workspace_revision=binding.workspace_revision,
                expected_write_generation=binding.write_generation)
            result = accept_workspace_command_in_uow(uow, actor, task["task_id"], value,
                idempotency_key=key, workspace_id=workspace_id,
                enqueue_operation=engineering_enqueuer(self.client, "workspace"))
            return _receipt(result.body)

    def query_operation(self, run_id, arguments):
        operation_id = _argument(arguments, "operation_id")
        with UnitOfWork(self.engine) as uow:
            _, _, run, request, now = current_run(uow, run_id)
            result = _result_in_uow(uow, run["source_command_id"], request, operation_id)
            return {"operation_id": operation_id, "state": "registered" if result else "accepted",
                    "execution_state": "registered" if result else "unknown",
                    "observed_at": now.astimezone(UTC).isoformat(), "result": result}

    def await_operation(self, run_id, tool_call_id, arguments):
        _identity(run_id, tool_call_id)
        operation_id = _argument(arguments, "operation_id")
        with UnitOfWork(self.engine) as uow:
            _, _, run, request, _ = current_run(uow, run_id)
            result = _result_in_uow(uow, run["source_command_id"], request, operation_id)
        if result is None:
            raise CallDeferred(metadata={"operation_id": operation_id})
        return result


def register_wait_in_uow(uow, client, run_id, tool_call_id, operation_id):
    """Call after saving the old Run history and releasing its active state in this transaction."""
    require_transaction(uow.connection)
    wait_id = "agent-wait-" + _identity(run_id, tool_call_id)
    run = uow.connection.execute(select(agent_runs).where(agent_runs.c.run_id == run_id)).mappings().one()
    request = RuntimeStartRequest.model_validate(run["start_json"])
    actor = actor_for_command(uow, run["source_command_id"])
    task, _ = lock_task_access(uow, actor, request.runtime_input.task_id, "task.command")
    require_ordinary_progress(uow.connection, task["task_id"], expected_version=task["version"],
        expected_control_revision=request.runtime_input.expected_task_control_revision,
        expected_input_validity_revision=request.runtime_input.expected_input_validity_revision)
    session = uow.connection.execute(select(agent_sessions).where(
        agent_sessions.c.session_id == request.runtime_input.session_id).with_for_update()).mappings().one()
    if (run["state"] in {"queued", "running"} or session["version"] != request.runtime_input.expected_session_version + 1
            or session["task_id"] != task["task_id"]):
        raise TaskBoundaryError("agent_wait_run_not_committed")
    _result_in_uow(uow, run["source_command_id"], request, operation_id)
    previous = uow.connection.execute(select(agent_operation_waits).where(
        agent_operation_waits.c.wait_condition_id == wait_id)).mappings().one_or_none()
    if previous is None:
        uow.connection.execute(insert(task_wait_conditions).values(wait_condition_id=wait_id,
            task_id=task["task_id"], required_for_completion=False, state="waiting",
            input_set_key=reference_key(task["project_id"], request.context.input_set_ref)))
        uow.connection.execute(insert(agent_operation_waits).values(wait_condition_id=wait_id,
            session_id=session["session_id"], from_run_id=run_id, tool_call_id=tool_call_id,
            operation_id=operation_id, control_revision=task["control_revision"],
            input_validity_revision=task["input_validity_revision"]))
    elif previous["operation_id"] != operation_id:
        raise TaskBoundaryError("agent_wait_identity_conflict")
    resume_ready_waits_in_uow(uow, client, session["session_id"])
    return EngineeringRef(kind="wait_condition", object_id=wait_id, revision="1")


def resume_ready_waits_in_uow(uow, client, session_id):
    """Merge ready notifications when another Run is active; otherwise queue one continuation."""
    require_transaction(uow.connection)
    waits = uow.connection.execute(select(agent_operation_waits).join(task_wait_conditions).where(
        agent_operation_waits.c.session_id == session_id,
        agent_operation_waits.c.continuation_run_id.is_(None),
        task_wait_conditions.c.state == "waiting").order_by(agent_operation_waits.c.wait_condition_id)).mappings().all()
    for wait in waits:
        try:
            with uow.connection.begin_nested():
                run = uow.connection.execute(select(agent_runs).where(
                    agent_runs.c.run_id == wait["from_run_id"])).mappings().one()
                request = RuntimeStartRequest.model_validate(run["start_json"])
                result = _result_in_uow(uow, run["source_command_id"], request, wait["operation_id"])
                if result is None:
                    continue
                values = {wait["tool_call_id"]: result}
                continuation = enqueue_wait_continuation_in_uow(uow, client, wait, _digest(values))
                if continuation is None:
                    return None
                uow.connection.execute(update(agent_operation_waits).where(
                    agent_operation_waits.c.wait_condition_id == wait["wait_condition_id"]).values(
                    continuation_run_id=continuation))
                uow.connection.execute(update(task_wait_conditions).where(
                    task_wait_conditions.c.wait_condition_id == wait["wait_condition_id"],
                    task_wait_conditions.c.state == "waiting").values(state="closed"))
                return continuation
        except (IdentityError, TaskBoundaryError):
            # Late results remain archived; a denied or fenced continuation is not reopened.
            continue
    return None


def notify_operation_in_uow(uow, client, operation_id):
    require_transaction(uow.connection)
    sessions = uow.connection.scalars(select(agent_operation_waits.c.session_id).join(task_wait_conditions).where(
        agent_operation_waits.c.operation_id == operation_id,
        agent_operation_waits.c.continuation_run_id.is_(None), task_wait_conditions.c.state == "waiting").distinct())
    for session_id in sessions:
        resume_ready_waits_in_uow(uow, client, session_id)


def load_deferred_results_in_uow(uow, run_id):
    require_transaction(uow.connection)
    run = uow.connection.execute(select(agent_runs).where(agent_runs.c.run_id == run_id)).mappings().one()
    request = RuntimeStartRequest.model_validate(run["start_json"])
    reference = request.runtime_input.deferred_results
    if reference is None:
        return None
    wait = uow.connection.execute(select(agent_operation_waits).where(
        agent_operation_waits.c.wait_condition_id == reference.object_id,
        agent_operation_waits.c.continuation_run_id == run_id)).mappings().one_or_none()
    if wait is None or wait["session_id"] != request.runtime_input.session_id:
        raise TaskBoundaryError("agent_deferred_results_not_found")
    result = _result_in_uow(uow, run["source_command_id"], request, wait["operation_id"])
    if result is None:
        raise TaskBoundaryError("agent_operation_unsettled")
    values = {wait["tool_call_id"]: result}
    if _digest(values) != reference.digest:
        raise TaskBoundaryError("agent_deferred_results_digest_mismatch")
    return values
