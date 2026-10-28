"""Atomically hand an engineering intent to DBOS in its application's UoW."""

from dbos import DBOSClient, EnqueueOptions, WorkflowSerializationFormat
from sqlalchemy import insert
from sqlalchemy.engine import Connection

from database.uow import require_transaction
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, queue_for
from packages.contracts.p1.engineering_commands import EngineeringWorkflowDispatch


def enqueue_engineering(
    connection: Connection, client: DBOSClient, dispatch: EngineeringWorkflowDispatch,
) -> str:
    """No independent commit or executor call; any failure rolls back the intent."""
    require_transaction(connection)
    queue = queue_for(dispatch.workflow_name)
    connection.execute(insert(workflow_bindings).values(
        workflow_id=dispatch.workflow_id, command_id=dispatch.command_id,
        business_kind=dispatch.business_kind, business_id=dispatch.business_id,
        process_type=dispatch.workflow_name, advance_revision=dispatch.advance_revision,
        workflow_name=dispatch.workflow_name, queue_name=queue,
        application_name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
        request_digest=dispatch.request_digest,
    ))
    options: EnqueueOptions = {
        "workflow_name": dispatch.workflow_name, "queue_name": queue,
        "workflow_id": dispatch.workflow_id, "workflow_id_reuse_policy": "return-existing",
        "app_version": APPLICATION_VERSION, "application_name": APPLICATION_NAME,
        "serialization_type": WorkflowSerializationFormat.PORTABLE,
    }
    client.enqueue_in_transaction(connection, options, dispatch.operation_id)
    return dispatch.workflow_id
