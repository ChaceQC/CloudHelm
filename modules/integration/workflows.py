"""Integration owns its durable workflow; checkpoints contain only operation IDs."""

from dbos import DBOS, WorkflowSerializationFormat

_execute = None


@DBOS.step(name="integration.merge_queue.stage.v1", retries_allowed=False)
def _merge_step(operation_id: str):
    if _execute is None:
        raise RuntimeError("integration_workflow_not_configured")
    return _execute(operation_id)


@DBOS.workflow(name="integration.merge_queue.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def merge_queue_stage(operation_id: str):
    return _merge_step(operation_id)


def register_merge_workflows(execute):
    global _execute
    _execute = execute
