"""Application adapters for the shared transactional DBOS handoff."""

from modules.workflow.engineering import enqueue_engineering
from packages.contracts.p1.engineering_commands import EngineeringWorkflowDispatch


def engineering_enqueuer(client, business_kind):
    names = {"project": "projects.source_import.v1", "workspace": "workspaces.operation.v1",
             "build": "delivery.build.v1", "deployment": "delivery.deployment_stage.v1",
             "integration": "integration.merge_queue.v1"}
    if business_kind not in names:
        raise ValueError("engineering_workflow_domain_invalid")

    def enqueue(uow, operation_id, command_id, business_id, advance_revision, request_digest):
        return enqueue_engineering(uow.connection, client, EngineeringWorkflowDispatch(
            command_id=command_id, operation_id=operation_id, workflow_id="engineering-" + operation_id,
            business_kind="project" if business_kind == "integration" else business_kind,
            business_id=business_id, advance_revision=advance_revision,
            workflow_name=names[business_kind], request_digest=request_digest,
        ))

    return enqueue


def build_enqueuer(client):
    enqueue = engineering_enqueuer(client, "build")

    def enqueue_build(uow, *, operation_id, command_id, build_id, advance_revision, request_digest):
        return enqueue(uow, operation_id, command_id, build_id, advance_revision, request_digest)

    return enqueue_build


def development_environment_enqueuer(client):
    def enqueue(uow, operation_id, command_id, environment_id, advance_revision, request_digest):
        return enqueue_engineering(uow.connection, client, EngineeringWorkflowDispatch(
            command_id=command_id, operation_id=operation_id, workflow_id="engineering-" + operation_id,
            business_kind="workspace", business_id=environment_id, advance_revision=advance_revision,
            workflow_name="workspaces.development_environment.v1", request_digest=request_digest,
        ))

    return enqueue
