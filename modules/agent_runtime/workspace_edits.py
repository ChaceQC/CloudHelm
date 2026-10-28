"""Developer edits use the existing digest-only workspace operation and wait chain."""

from pydantic import ValidationError
from sqlalchemy import select

from database.commands import commands, get_by_id
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.identity.actors import actor_for_command
from modules.workflow.engineering_enqueuers import engineering_enqueuer
from modules.workspaces.commands import accept_workspace_command_in_uow
from modules.workspaces.operations import read_workspace_operation, read_workspace_row
from modules.workspaces.queries import workspace_read_spec_in_uow
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.workspace_requests import MutateWorkspaceFileRequest, WorkspaceCommandResult
from packages.contracts.p2.workspace_edits import WORKSPACE_EDIT_SCHEMAS
from .admission import current_run
from .operations import _digest, _identity, _receipt


class WorkspaceEditGateway:
    def __init__(self, engine, client, prepare_edit, stage_content):
        self.engine, self.client = engine, client
        self.prepare_edit, self.stage_content = prepare_edit, stage_content

    def submit(self, run_id, tool_call_id, name, arguments):
        try:
            query = WORKSPACE_EDIT_SCHEMAS[name].model_validate(arguments)
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
                previous_id = uow.connection.scalar(select(commands.c.command_id).where(
                    commands.c.idempotency_key.startswith(prefix), commands.c.project_id == task["project_id"],
                    commands.c.resource_kind == "task", commands.c.resource_id == task["task_id"],
                    commands.c.caller_kind == actor.principal.kind, commands.c.subject_id == actor.principal.subject_id,
                    commands.c.delegator_id == actor.principal.delegator_id))
                if previous_id is not None:
                    previous = get_by_id(uow.connection, previous_id)
                    result = WorkspaceCommandResult.model_validate(previous.result)
                    if (previous.envelope.idempotency_key != key or result.kind != "mutate"
                            or result.workspace_id != query.workspace_id):
                        raise TaskBoundaryError("agent_tool_call_identity_conflict")
                    if result.outcome == "accepted":
                        read_workspace_operation(uow.connection, result.operation_id)
                    return _receipt(result)
                spec = workspace_read_spec_in_uow(uow, actor, query.workspace_id)
                if self.prepare_edit is None or self.stage_content is None:
                    raise TaskBoundaryError("agent_workspace_editor_unavailable")
                before, replacement, content = self.prepare_edit(spec, name, query)
                value = MutateWorkspaceFileRequest(expected_version=task["version"],
                    expected_control_revision=request.runtime_input.expected_task_control_revision,
                    expected_input_validity_revision=request.runtime_input.expected_input_validity_revision,
                    input_set_ref=request.context.input_set_ref,
                    expected_workspace_revision=query.expected_workspace_revision,
                    expected_write_generation=query.expected_write_generation,
                    expected_manifest_digest=query.expected_manifest_digest,
                    action="write", path=query.path, expected_file=before, replacement=replacement)
            # Staging is inert storage, outside the short command transaction.
            if self.stage_content(content) != replacement.content_digest:
                raise WorkspaceFileError("workspace_mutation_content_mismatch")
            with UnitOfWork(self.engine) as uow:
                current_run(uow, run_id)
                result = accept_workspace_command_in_uow(uow, actor, task["task_id"], value,
                    idempotency_key=key, workspace_id=query.workspace_id,
                    enqueue_operation=engineering_enqueuer(self.client, "workspace"))
                return _receipt(result.body)
        except (TaskBoundaryError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}
