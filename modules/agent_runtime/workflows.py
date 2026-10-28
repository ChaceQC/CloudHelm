"""Worker-only DBOS registration; parameters and checkpoints contain bounded facts."""

from dbos import DBOS, WorkflowSerializationFormat

from .registration import WORKFLOW_NAME

_application = None


@DBOS.step(name="agent_runtime.advance.apply.v1", retries_allowed=False)
def _advance(run_id: str):
    return _application.advance_session(run_id)


@DBOS.workflow(name=WORKFLOW_NAME, serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def advance_session(run_id: str):
    return _advance(run_id)


def register_agent_workflows(application):
    global _application
    _application = application
