"""Workspaces-owned bounded physical operation workflow."""

from dbos import DBOS, WorkflowSerializationFormat

_execute = None


@DBOS.step(name="workspaces.operation.apply.v1", retries_allowed=False)
def _workspace_step(operation_id: str):
    if _execute is None:
        raise RuntimeError("workspace_workflow_not_configured")
    return _execute(operation_id)


@DBOS.workflow(name="workspaces.operation.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def workspace_operation(operation_id: str):
    return _workspace_step(operation_id)


def register_workspace_workflows(execute):
    global _execute
    if not callable(execute):
        raise TypeError("workspace_executor_required")
    _execute = execute
