"""Current-authority gateway for fixed development workspace checks."""

from pydantic import ValidationError
from sqlalchemy import select

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.tables import work_items
from modules.identity.actors import actor_for_command
from modules.identity.errors import IdentityError
from modules.workspaces.development_queries import read_development_environment
from modules.workspaces.development_tables import workspace_development_environment_operations as environment_operations
from modules.workspaces.operations import pending_workspace_operations, read_workspace_operation, read_workspace_row
from modules.workspaces.queries import workspace_read_spec_in_uow
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p2.workspace_checks import WorkspaceCheck
from .admission import current_run


class WorkspaceCheckGateway:
    def __init__(self, engine, runner):
        self.engine, self.runner = engine, runner

    def query(self, run_id, arguments):
        try:
            query = WorkspaceCheck.model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_workspace_arguments_invalid"}
        try:
            initial_spec, initial_environment_revision = None, None
            for stage in range(2):
                with UnitOfWork(self.engine) as uow:
                    task, _, run, request, _ = current_run(uow, run_id)
                    actor = actor_for_command(uow, run["source_command_id"])
                    task, _ = lock_task_access(uow, actor, task["task_id"], "workspace.write")
                    workspace = read_workspace_row(uow.connection, query.workspace_id)
                    if (workspace["project_id"] != task["project_id"]
                            or workspace["task_id"] != task["task_id"]
                            or workspace["work_item_id"] != request.context.work_item_id):
                        raise TaskBoundaryError("agent_workspace_not_found", status_code=404)
                    item_state = uow.connection.scalar(select(work_items.c.state).where(
                        work_items.c.task_id == task["task_id"],
                        work_items.c.work_item_id == request.context.work_item_id))
                    if item_state not in {"ready", "running", "submitted"}:
                        raise TaskBoundaryError("workspace_work_item_closed")
                    spec = workspace_read_spec_in_uow(uow, actor, query.workspace_id)
                    if spec.binding.workspace_revision != query.expected_workspace_revision:
                        raise TaskBoundaryError("workspace_revision_conflict")
                    if spec.binding.write_generation != query.expected_write_generation:
                        raise TaskBoundaryError("workspace_write_generation_conflict")
                    for pending in pending_workspace_operations(uow.connection, task["task_id"]):
                        intent, _ = read_workspace_operation(uow.connection, pending.operation_ref.object_id)
                        if intent.result.workspace_id == query.workspace_id and intent.request.kind == "mutate":
                            raise TaskBoundaryError("workspace_operation_pending")
                    environment = read_development_environment(uow.connection, query.environment_id, for_update=True)
                    if (environment["project_id"] != task["project_id"]
                            or environment["task_id"] != task["task_id"]
                            or environment["work_item_id"] != request.context.work_item_id
                            or environment["workspace_id"] != query.workspace_id):
                        raise TaskBoundaryError("agent_workspace_environment_not_found", status_code=404)
                    if environment["binding_json"] != spec.binding.model_dump(mode="json"):
                        raise TaskBoundaryError("workspace_development_binding_stale")
                    if environment["source_manifest_digest"] != query.expected_manifest_digest:
                        raise TaskBoundaryError("workspace_manifest_mismatch")
                    if environment["state"] != "ready":
                        raise TaskBoundaryError("agent_workspace_environment_not_ready")
                    pending = uow.connection.scalar(select(environment_operations.c.operation_id).where(
                        environment_operations.c.environment_id == query.environment_id,
                        environment_operations.c.operation_state.in_(("pending", "unknown"))).limit(1))
                    if pending is not None:
                        raise TaskBoundaryError("workspace_development_operation_pending")
                    if stage == 0:
                        initial_spec, initial_environment_revision = spec, environment["environment_revision"]
                    elif spec != initial_spec or environment["environment_revision"] != initial_environment_revision:
                        raise TaskBoundaryError("agent_workspace_check_environment_changed")
                if stage == 0:
                    if self.runner is None:
                        raise TaskBoundaryError("agent_workspace_check_unavailable")
                    try:
                        result = self.runner(spec, query)
                    except (TaskBoundaryError, WorkspaceFileError, IdentityError):
                        raise
                    except Exception:
                        raise TaskBoundaryError("agent_workspace_check_unavailable") from None
            return result
        except (TaskBoundaryError, WorkspaceFileError, IdentityError) as error:
            return {"status": "rejected", "code": error.code}
