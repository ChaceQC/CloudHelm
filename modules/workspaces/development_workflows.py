"""Workspace-owned durable handoff for bounded environment transitions."""

from dbos import DBOS, WorkflowSerializationFormat

_execute = None


@DBOS.step(name="workspaces.development_environment.apply.v1", retries_allowed=False)
def _development_environment_step(operation_id: str):
    if _execute is None:
        raise RuntimeError("workspace_development_workflow_not_configured")
    return _execute(operation_id)


@DBOS.workflow(name="workspaces.development_environment.v1",
               serialization_type=WorkflowSerializationFormat.PORTABLE, max_recovery_attempts=3)
def development_environment_operation(operation_id: str):
    return _development_environment_step(operation_id)


def register_development_environment_workflows(execute):
    global _execute
    if not callable(execute):
        raise TypeError("workspace_development_executor_required")
    _execute = execute
