"""Bind and enqueue in the caller's SQLAlchemy transaction through public DBOS."""

from dbos import DBOSClient, EnqueueOptions, WorkflowSerializationFormat
from sqlalchemy import insert
from sqlalchemy.engine import Connection

from database.uow import require_transaction
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, queue_for
from packages.contracts.p1.commands import WorkflowDispatch


def bind_and_enqueue(
    connection: Connection, client: DBOSClient, dispatch: WorkflowDispatch
) -> str:
    """No wait or commit; SDK/SQL failures roll back with every domain write."""
    require_transaction(connection)
    try:
        dispatch = WorkflowDispatch.model_validate(dispatch.model_dump(mode="python"))
    except (AttributeError, ValueError, TypeError):
        raise ValueError("workflow_dispatch_invalid") from None
    queue_name = queue_for(dispatch.workflow_name)
    connection.execute(insert(workflow_bindings).values(
        workflow_id=dispatch.workflow_id, command_id=dispatch.command_id,
        business_kind="task", business_id=dispatch.task_id,
        process_type=dispatch.workflow_name, advance_revision=dispatch.advance_revision,
        workflow_name=dispatch.workflow_name, queue_name=queue_name,
        application_name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
        request_digest=dispatch.request_digest,
    ))
    options: EnqueueOptions = {
        "workflow_name": dispatch.workflow_name,
        "queue_name": queue_name,
        "workflow_id": dispatch.workflow_id,
        "workflow_id_reuse_policy": "return-existing",
        "app_version": APPLICATION_VERSION,
        "application_name": APPLICATION_NAME,
        "serialization_type": WorkflowSerializationFormat.PORTABLE,
    }
    client.enqueue_in_transaction(connection, options, dispatch.command_id)
    return dispatch.workflow_id
