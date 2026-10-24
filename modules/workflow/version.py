"""Current Hub workflow baseline; independent of release and design versions."""

from packages.contracts.p1.commands import WorkflowName
from packages.contracts.p1.engineering_commands import EngineeringWorkflowName

APPLICATION_NAME = "cloudhelm-hub"
APPLICATION_VERSION = "0.5.0"
DBOS_SDK_VERSION = "3.2.0"
DBOS_SCHEMA = "dbos"
INITIAL_WORKFLOW: WorkflowName = "collaboration.task_initial.v1"
CONTROL_WORKFLOW: WorkflowName = "collaboration.task_control.v1"

SOURCE_IMPORT_WORKFLOW: EngineeringWorkflowName = "projects.source_import.v1"
WORKSPACE_WORKFLOW: EngineeringWorkflowName = "workspaces.operation.v1"
DEVELOPMENT_ENVIRONMENT_WORKFLOW: EngineeringWorkflowName = "workspaces.development_environment.v1"
BUILD_WORKFLOW: EngineeringWorkflowName = "delivery.build.v1"

WORKFLOW_QUEUES: dict[WorkflowName | EngineeringWorkflowName, str] = {
    INITIAL_WORKFLOW: "orchestration",
    CONTROL_WORKFLOW: "control",
    SOURCE_IMPORT_WORKFLOW: "engineering",
    WORKSPACE_WORKFLOW: "engineering",
    DEVELOPMENT_ENVIRONMENT_WORKFLOW: "engineering",
    BUILD_WORKFLOW: "engineering",
}


def queue_for(workflow_name: WorkflowName | EngineeringWorkflowName) -> str:
    try:
        return WORKFLOW_QUEUES[workflow_name]
    except KeyError:
        raise ValueError("workflow_not_registered") from None
