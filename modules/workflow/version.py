"""Current Hub workflow baseline; independent of release and design versions."""

from packages.contracts.p1.commands import WorkflowName

APPLICATION_NAME = "cloudhelm-hub"
APPLICATION_VERSION = "0.2.0"
DBOS_SDK_VERSION = "3.2.0"
DBOS_SCHEMA = "dbos"
INITIAL_WORKFLOW: WorkflowName = "collaboration.task_initial.v1"
CONTROL_WORKFLOW: WorkflowName = "collaboration.task_control.v1"

WORKFLOW_QUEUES: dict[WorkflowName, str] = {
    INITIAL_WORKFLOW: "orchestration",
    CONTROL_WORKFLOW: "control",
}


def queue_for(workflow_name: WorkflowName) -> str:
    try:
        return WORKFLOW_QUEUES[workflow_name]
    except KeyError:
        raise ValueError("workflow_not_registered") from None
