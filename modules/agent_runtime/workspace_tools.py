"""Current, authorized WorkItem files exposed through read-only Gateway routes."""

from pydantic import ValidationError

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.identity.actors import actor_for_command
from modules.workspaces.operations import read_workspace_row
from modules.workspaces.queries import workspace_read_spec_in_uow
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p2.workspace_tools import WORKSPACE_TOOL_SCHEMAS
from .admission import current_run


class WorkspaceCodeGateway:
    def __init__(self, engine, reader):
        self.engine, self.reader = engine, reader

    def query(self, run_id, name, arguments):
        try:
            query = WORKSPACE_TOOL_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_workspace_arguments_invalid"}
        try:
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                workspace = read_workspace_row(uow.connection, query.workspace_id)
                if (workspace["project_id"] != task["project_id"]
                        or workspace["task_id"] != task["task_id"]
                        or workspace["work_item_id"] != request.context.work_item_id):
                    raise TaskBoundaryError("agent_workspace_not_found", status_code=404)
                actor = actor_for_command(uow, run["source_command_id"])
                spec = workspace_read_spec_in_uow(uow, actor, query.workspace_id)
                if self.reader is None:
                    raise TaskBoundaryError("agent_workspace_reader_unavailable")
                return self.reader(spec, name, query)
        except (TaskBoundaryError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}
