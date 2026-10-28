"""Developer environment tools use the existing Workspace lifecycle and Runner."""

from pydantic import ValidationError
from sqlalchemy import select

from database.commands import commands, get_by_id
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.identity.actors import actor_for_command
from modules.workspaces.development_queries import (
    query_development_environment_in_uow, query_development_operation_in_uow,
    read_development_environment,
)
from modules.workspaces.development_tables import workspace_development_environments as environments
from modules.workspaces.operations import read_workspace_row
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p0.core_contracts import AcceptedReceipt
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.workspace_development_requests import (
    DisposeWorkspaceDevelopmentRequest, PrepareWorkspaceDevelopmentRequest,
    ResumeWorkspaceDevelopmentRequest, SuspendWorkspaceDevelopmentRequest,
    WorkspaceDevelopmentCommandResult,
)
from packages.contracts.p2.workspace_environment import WORKSPACE_ENVIRONMENT_SCHEMAS
from .admission import current_run
from .operations import _digest, _identity


def _development_receipt(result):
    if result.outcome != "accepted":
        return {"status": "rejected", "code": result.code}
    reference = EngineeringRef(kind="operation", object_id=result.operation_id,
        revision="p1-workspace-development-operation-r1", authority="workspace-development",
        digest=result.request_digest, digest_algorithm="sha256")
    return AcceptedReceipt(operation_id=result.operation_id, request_digest=result.request_digest,
        query_ref=reference, wait_ref=reference).model_dump(mode="json")


class WorkspaceEnvironmentGateway:
    def __init__(self, engine, application, log_reader):
        self.engine, self.application, self.log_reader = engine, application, log_reader

    def submit(self, run_id, tool_call_id, name, arguments):
        try:
            query = WORKSPACE_ENVIRONMENT_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_workspace_arguments_invalid"}
        try:
            prefix = "agent-tool-" + _identity(run_id, tool_call_id)
            key = prefix + "-" + _digest([name, query.model_dump(mode="json")])[7:]
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                actor = actor_for_command(uow, run["source_command_id"])
                task, _ = lock_task_access(uow, actor, task["task_id"], "workspace.write")
                workspace = read_workspace_row(uow.connection, query.workspace_id, for_update=True)
                if (workspace["project_id"] != task["project_id"]
                        or workspace["task_id"] != task["task_id"]
                        or workspace["work_item_id"] != request.context.work_item_id):
                    raise TaskBoundaryError("agent_workspace_not_found", status_code=404)
                action = "prepare" if name == "workspace.prepare_environment" else query.action
                previous_id = uow.connection.scalar(select(commands.c.command_id).where(
                    commands.c.idempotency_key.startswith(prefix), commands.c.project_id == task["project_id"],
                    commands.c.resource_kind == "task", commands.c.resource_id == task["task_id"],
                    commands.c.caller_kind == actor.principal.kind, commands.c.subject_id == actor.principal.subject_id,
                    commands.c.delegator_id == actor.principal.delegator_id))
                if previous_id is not None:
                    previous = get_by_id(uow.connection, previous_id)
                    if (previous.envelope.idempotency_key != key
                            or previous.envelope.request_schema_revision != "p1-workspace-development-" + action + "-r1"):
                        raise TaskBoundaryError("agent_tool_call_identity_conflict")
                    result = WorkspaceDevelopmentCommandResult.model_validate(previous.result)
                    if (result.action != action or result.task_id != task["task_id"]
                            or result.workspace_id != query.workspace_id
                            or action != "prepare" and result.environment_id != query.environment_id):
                        raise TaskBoundaryError("agent_tool_call_identity_conflict")
                    if result.outcome == "accepted":
                        query_development_operation_in_uow(uow, actor, result.environment_id, result.operation_id)
                    return _development_receipt(result)
                if action != "prepare":
                    environment = read_development_environment(uow.connection, query.environment_id)
                    if (environment["project_id"] != task["project_id"]
                            or environment["task_id"] != task["task_id"]
                            or environment["work_item_id"] != request.context.work_item_id
                            or environment["workspace_id"] != query.workspace_id):
                        raise TaskBoundaryError("agent_workspace_environment_not_found", status_code=404)
                if self.application is None:
                    raise TaskBoundaryError("agent_workspace_environment_unavailable")
                common = dict(expected_version=task["version"],
                    expected_control_revision=request.runtime_input.expected_task_control_revision,
                    expected_input_validity_revision=request.runtime_input.expected_input_validity_revision,
                    input_set_ref=request.context.input_set_ref,
                    expected_workspace_revision=query.expected_workspace_revision,
                    expected_write_generation=query.expected_write_generation)
                if action == "prepare":
                    value = PrepareWorkspaceDevelopmentRequest(**common)
                else:
                    classes = {"suspend": SuspendWorkspaceDevelopmentRequest,
                               "resume": ResumeWorkspaceDevelopmentRequest,
                               "dispose": DisposeWorkspaceDevelopmentRequest}
                    value = classes[action](**common, expected_environment_revision=query.expected_environment_revision,
                        expected_data_revision=query.expected_data_revision,
                        expected_data_generation=query.expected_data_generation)
            admit = lambda uow: current_run(uow, run_id)
            if action == "prepare":
                result = self.application.prepare(actor, query.workspace_id, value, key, admit=admit)
            else:
                result = self.application.control(actor, query.environment_id, value, key, admit=admit)
            return _development_receipt(result.body)
        except (TaskBoundaryError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}

    def query(self, run_id, name, arguments):
        try:
            query = WORKSPACE_ENVIRONMENT_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_workspace_arguments_invalid"}
        try:
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                actor = actor_for_command(uow, run["source_command_id"])
                task, _ = lock_task_access(uow, actor, task["task_id"], "resource.read")
                workspace = read_workspace_row(uow.connection, query.workspace_id)
                if (workspace["project_id"] != task["project_id"]
                        or workspace["task_id"] != task["task_id"]
                        or workspace["work_item_id"] != request.context.work_item_id):
                    raise TaskBoundaryError("agent_workspace_not_found", status_code=404)
                if name == "workspace.environment_status":
                    environment_id = uow.connection.scalar(select(environments.c.environment_id).where(
                        environments.c.workspace_id == query.workspace_id,
                    ).order_by(environments.c.created_at.desc(), environments.c.environment_id.desc()).limit(1))
                    if environment_id is None:
                        return {"workspace_id": query.workspace_id, "environment": None}
                else:
                    environment_id = query.environment_id
                row = read_development_environment(uow.connection, environment_id)
                if (row["project_id"] != task["project_id"] or row["task_id"] != task["task_id"]
                        or row["work_item_id"] != request.context.work_item_id
                        or row["workspace_id"] != query.workspace_id):
                    raise TaskBoundaryError("agent_workspace_environment_not_found", status_code=404)
                if name == "workspace.environment_status":
                    view = query_development_environment_in_uow(uow, actor, environment_id)
                    row = read_development_environment(uow.connection, environment_id)
                    return {"workspace_id": query.workspace_id, "environment": {
                        **view.model_dump(mode="json"), "data_revision": row["data_revision"],
                        "data_generation": row["data_generation"]}}
                if self.log_reader is None:
                    raise TaskBoundaryError("agent_workspace_environment_logs_unavailable")
            try:
                logs = self.log_reader(environment_id, service=query.service, max_lines=query.max_lines, max_bytes=8192)
            finally:
                with UnitOfWork(self.engine) as uow:
                    current_run(uow, run_id)
            return logs
        except (TaskBoundaryError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}
