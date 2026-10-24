"""Durably stage approved plans; remote physical progression belongs to P1.4-02."""

from dbos import DBOS, WorkflowSerializationFormat
from sqlalchemy import select

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_application import delivery_context
from modules.delivery.deployment_control import approved_preflight
from modules.delivery.deployment_store import read_object
from modules.delivery.deployment_tables import deployment_approvals
from modules.identity.actors import actor_for_command
from modules.sync.events import append_event
from modules.sync.tables import event_log
from packages.contracts.p1.delivery_records import DeploymentStagedEvent

_engine = None


@DBOS.step(name="delivery.deployment_stage.apply.v1", retries_allowed=False)
def _stage(operation_id: str):
    if _engine is None:
        raise RuntimeError("deployment_staging_not_configured")
    with UnitOfWork(_engine) as uow:
        rows = uow.connection.execute(select(deployment_approvals).where(
            deployment_approvals.c.value_json["operation_id"].astext == operation_id,
        ).limit(2)).mappings().all()
        if len(rows) != 1:
            raise TaskBoundaryError("deployment_operation_not_found")
        row = rows[0]
        actor = actor_for_command(uow, row["command_id"])
        context = delivery_context(uow, actor, row["project_id"], "deployment.approve")
        approval = read_object(uow.connection, row["project_id"], "approval", row["plan_id"]).value
        event_id = "deployment-staged-" + approval.plan_digest[7:]
        if existing := uow.connection.scalar(select(event_log.c.payload).where(event_log.c.event_id == event_id)):
            return existing
        try:
            approved_preflight(context, row["plan_id"], approval.plan_digest)
            code = "remote_agent_transport_not_connected"
        except TaskBoundaryError as error:
            code = error.code
        result = DeploymentStagedEvent(operation_id=operation_id, plan_id=row["plan_id"], blocking_code=code)
        append_event(uow.connection, command_id=row["command_id"], project_id=row["project_id"],
            aggregate_kind="deployment", aggregate_id=operation_id, aggregate_version=1, event_id=event_id,
            event_type="deployment.staged", schema_version="p1-deployment-staged-r1", payload=result)
        return result.model_dump(mode="json")


@DBOS.workflow(name="delivery.deployment_stage.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def deployment_stage(operation_id: str):
    return _stage(operation_id)


def register_deployment_workflows(engine):
    global _engine
    _engine = engine
