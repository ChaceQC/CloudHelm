"""Agent routes onto the existing candidate freeze and fixed-input build chains."""

from pydantic import ValidationError
from sqlalchemy import select

from database.commands import commands, get_by_id
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.commands import accept_build
from modules.delivery.queries import build_view, read_build_intent
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.workflow.engineering_enqueuers import build_enqueuer, engineering_enqueuer
from modules.workspaces.commands import accept_workspace_command_in_uow
from modules.workspaces.operations import REQUEST_SCHEMAS, read_workspace_row
from modules.workspaces.queries import query_workspace_operation_in_uow, read_physical_candidate_in_uow
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p0.core_contracts import AcceptedReceipt
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_requests import BUILD_REQUEST_SCHEMA, BuildCommandResult, RequestBuildRequest
from packages.contracts.p1.workspace_candidates import workspace_runtime_scope_id
from packages.contracts.p1.workspace_requests import SubmitWorkspaceCandidateRequest, WorkspaceCommandResult
from packages.contracts.p2.workspace_builds import WORKSPACE_BUILD_SCHEMAS
from .admission import current_run
from .operations import _digest, _identity, _receipt


def _build_receipt(result):
    if result.outcome != "accepted":
        return {"status": "rejected", "code": result.code}
    reference = EngineeringRef(kind="operation", object_id=result.operation_id,
        revision=BUILD_REQUEST_SCHEMA, authority="delivery",
        digest=result.request_digest, digest_algorithm="sha256")
    return AcceptedReceipt(operation_id=result.operation_id, request_digest=result.request_digest,
        query_ref=reference, wait_ref=reference).model_dump(mode="json")


def _previous(uow, actor, task, request, name, query, prefix, key):
    previous_id = uow.connection.scalar(select(commands.c.command_id).where(
        commands.c.idempotency_key.startswith(prefix), commands.c.project_id == task["project_id"],
        commands.c.resource_kind == "task", commands.c.resource_id == task["task_id"],
        commands.c.caller_kind == actor.principal.kind, commands.c.subject_id == actor.principal.subject_id,
        commands.c.delegator_id == actor.principal.delegator_id))
    if previous_id is None:
        return None
    previous = get_by_id(uow.connection, previous_id)
    schema = REQUEST_SCHEMAS["candidate"] if name == "workspace.submit_candidate" else BUILD_REQUEST_SCHEMA
    action = "candidate.submit" if name == "workspace.submit_candidate" else "operation.request"
    if (previous.envelope.idempotency_key != key or previous.envelope.request_schema_revision != schema
            or previous.envelope.action != action):
        raise TaskBoundaryError("agent_tool_call_identity_conflict")
    try:
        if name == "workspace.submit_candidate":
            result = WorkspaceCommandResult.model_validate(previous.result)
            if (result.kind != "candidate" or result.task_id != task["task_id"]
                    or result.workspace_id != query.workspace_id
                    or result.binding is not None and result.binding.work_item_id != request.context.work_item_id):
                raise TaskBoundaryError("agent_tool_call_identity_conflict")
            if result.outcome == "accepted":
                query_workspace_operation_in_uow(uow, actor, query.workspace_id, result.operation_id)
            return _receipt(result)
        result = BuildCommandResult.model_validate(previous.result)
    except ValidationError:
        raise TaskBoundaryError("agent_tool_call_identity_conflict") from None
    if result.task_id != task["task_id"] or result.project_id != task["project_id"]:
        raise TaskBoundaryError("agent_tool_call_identity_conflict")
    if result.outcome == "accepted":
        _, record = read_build_intent(uow.connection, result.operation_id)
        binding = record.fixed_inputs.candidate.binding
        if (record.fixed_inputs.candidate.candidate_id != query.candidate_id
                or binding.workspace_id != query.workspace_id or binding.work_item_id != request.context.work_item_id):
            raise TaskBoundaryError("agent_tool_call_identity_conflict")
        authorize_current(uow, actor, AuthoritativeResource(
            task["project_id"], "operation", result.operation_id, task_id=task["task_id"]), "operation.query")
    return _build_receipt(result)


class WorkspaceBuildGateway:
    def __init__(self, engine, client, definition_loader, result_reader):
        self.engine, self.client = engine, client
        self.definition_loader, self.result_reader = definition_loader, result_reader

    def submit(self, run_id, tool_call_id, name, arguments):
        try:
            query = WORKSPACE_BUILD_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_workspace_arguments_invalid"}
        try:
            prefix = "agent-tool-" + _identity(run_id, tool_call_id)
            key = prefix + "-" + _digest([name, query.model_dump(mode="json")])[7:]
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                actor = actor_for_command(uow, run["source_command_id"])
                action = "candidate.submit" if name == "workspace.submit_candidate" else "operation.request"
                task, _ = lock_task_access(uow, actor, task["task_id"], action)
                previous = _previous(uow, actor, task, request, name, query, prefix, key)
                if name == "workspace.submit_candidate":
                    workspace = read_workspace_row(uow.connection, query.workspace_id, for_update=True)
                    if (workspace["project_id"] != task["project_id"] or workspace["task_id"] != task["task_id"]
                            or workspace["work_item_id"] != request.context.work_item_id):
                        raise TaskBoundaryError("agent_workspace_not_found", status_code=404)
                else:
                    snapshot = read_physical_candidate_in_uow(
                        uow, actor, query.workspace_id, query.candidate_id).snapshot
                    binding = snapshot.binding
                    if (snapshot.candidate_id != query.candidate_id or binding.workspace_id != query.workspace_id
                            or binding.project_id != task["project_id"] or binding.task_id != task["task_id"]
                            or binding.work_item_id != request.context.work_item_id):
                        raise TaskBoundaryError("agent_workspace_candidate_not_found", status_code=404)
                if previous is not None:
                    return previous
                if name == "workspace.submit_candidate":
                    value = SubmitWorkspaceCandidateRequest(expected_version=task["version"],
                        expected_control_revision=request.runtime_input.expected_task_control_revision,
                        expected_input_validity_revision=request.runtime_input.expected_input_validity_revision,
                        input_set_ref=request.context.input_set_ref,
                        expected_workspace_revision=query.expected_workspace_revision,
                        expected_write_generation=query.expected_write_generation,
                        expected_manifest_digest=query.expected_manifest_digest)
                    result = accept_workspace_command_in_uow(uow, actor, task["task_id"], value,
                        idempotency_key=key, workspace_id=query.workspace_id,
                        runtime_scope_for=workspace_runtime_scope_id,
                        enqueue_operation=engineering_enqueuer(self.client, "workspace"))
                    return _receipt(result.body)
                if self.definition_loader is None:
                    raise TaskBoundaryError("agent_build_definition_unavailable")
                acceptance_ref = request.context.acceptance_assets_ref
            definition = self.definition_loader(snapshot, acceptance_ref)
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                actor = actor_for_command(uow, run["source_command_id"])
                task, _ = lock_task_access(uow, actor, task["task_id"], "operation.request")
                previous = _previous(uow, actor, task, request, name, query, prefix, key)
                if previous is not None:
                    return previous
                value = RequestBuildRequest(expected_version=task["version"],
                    expected_control_revision=request.runtime_input.expected_task_control_revision,
                    expected_input_validity_revision=request.runtime_input.expected_input_validity_revision,
                    input_set_ref=request.context.input_set_ref, candidate_id=query.candidate_id, definition=definition)
                result = accept_build(uow, actor, task["task_id"], value, idempotency_key=key,
                    enqueue_operation=build_enqueuer(self.client))
                return _build_receipt(result.body)
        except (TaskBoundaryError, IdentityError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}

    def query(self, run_id, name, arguments):
        try:
            query = WORKSPACE_BUILD_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_workspace_arguments_invalid"}
        try:
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                actor = actor_for_command(uow, run["source_command_id"])
                task, _ = lock_task_access(uow, actor, task["task_id"], "resource.read")
                row, record = read_build_intent(uow.connection, query.operation_id)
                operation_actor = actor_for_command(uow, record.command_id)
                if (row["project_id"] != task["project_id"] or row["task_id"] != task["task_id"]
                        or record.fixed_inputs.candidate.binding.work_item_id != request.context.work_item_id
                        or operation_actor.principal != actor.principal):
                    raise TaskBoundaryError("agent_operation_not_found", status_code=404)
                authorize_current(uow, actor, AuthoritativeResource(
                    task["project_id"], "operation", query.operation_id, task_id=task["task_id"]), "operation.query")
                view = build_view(uow.connection, record).model_dump(mode="json")
                if self.result_reader is None:
                    raise TaskBoundaryError("agent_build_result_unavailable")
            try:
                diagnostics = self.result_reader(record, log_role=query.log_role,
                    log_offset=query.log_offset, max_bytes=query.max_bytes)
            finally:
                with UnitOfWork(self.engine) as uow:
                    current_run(uow, run_id)
            return {"build": view, "diagnostics": diagnostics}
        except (TaskBoundaryError, IdentityError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}
