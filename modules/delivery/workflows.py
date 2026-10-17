"""Delivery-owned build workflow; accepted requests are not successful builds."""

from dbos import DBOS, WorkflowSerializationFormat

_execute = None


@DBOS.step(name="delivery.build.apply.v1", retries_allowed=False)
def _build_step(operation_id: str):
    if _execute is None:
        raise RuntimeError("build_workflow_not_configured")
    return _execute(operation_id)


@DBOS.workflow(name="delivery.build.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def build(operation_id: str):
    return _build_step(operation_id)


def register_build_workflows(execute):
    global _execute
    if not callable(execute):
        raise TypeError("build_executor_required")
    _execute = execute
