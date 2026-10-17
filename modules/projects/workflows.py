"""Projects-owned source workflow; DBOS stores the operation identity only."""

from dbos import DBOS, WorkflowSerializationFormat

_execute = None


@DBOS.step(name="projects.source_import.apply.v1", retries_allowed=False)
def _source_import_step(operation_id: str):
    if _execute is None:
        raise RuntimeError("source_workflow_not_configured")
    return _execute(operation_id)


@DBOS.workflow(name="projects.source_import.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def source_import(operation_id: str):
    return _source_import_step(operation_id)


def register_source_workflows(execute):
    global _execute
    if not callable(execute):
        raise TypeError("source_executor_required")
    _execute = execute
