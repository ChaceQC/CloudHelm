"""Durable preview handoff and bounded periodic reconciliation."""

from datetime import datetime

from dbos import DBOS, WorkflowSerializationFormat

_execute = None
_maintain = None


@DBOS.step(name="workspaces.preview.apply.v1", retries_allowed=False)
def _preview_step(operation_id: str):
    if _execute is None:
        raise RuntimeError("preview_workflow_not_configured")
    return _execute(operation_id)


@DBOS.workflow(name="workspaces.preview.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def preview_operation(operation_id: str):
    return _preview_step(operation_id)


@DBOS.step(name="workspaces.preview.maintenance.step.v1", retries_allowed=False)
def _maintenance_step():
    if _maintain is None:
        raise RuntimeError("preview_maintenance_not_configured")
    return _maintain()


@DBOS.workflow(name="workspaces.preview.maintenance.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def preview_maintenance(scheduled_at: datetime, context):
    return _maintenance_step()


def register_preview_workflows(execute, maintain):
    global _execute, _maintain
    if not callable(execute) or not callable(maintain):
        raise TypeError("preview_executor_and_maintenance_required")
    _execute, _maintain = execute, maintain
