"""One UoW for current access, command identity, immutable delivery data and enqueue."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.compose import ComposeParseError
from modules.delivery.deployment_control import approve_plan, approved_preflight
from modules.delivery.deployment_planning import create_plan
from modules.delivery.deployment_store import lock_binding, read_object
from modules.delivery.deployment_tables import deployment_approvals
from modules.delivery.environment_commands import create_config, create_environment
from modules.delivery.release_commands import create_release
from modules.identity.actors import AuthoritativeResource, validate_actor
from modules.identity.authorization import authorize_current
from modules.identity.locking import lock_current_subject
from modules.sync.events import append_event
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.delivery_records import DeploymentView, EnvironmentView
from packages.contracts.p1.delivery_requests import (
    ApproveDeploymentPlanRequest, CreateDeploymentPlanRequest, CreateEnvironmentConfigRequest,
    CreateEnvironmentRequest, CreateReleaseRequest, DeliveryCommandBody, DeliveryCommandResult, DeliveryHttpResult,
)


@dataclass
class DeliveryContext:
    uow: UnitOfWork
    actor: object
    project_id: str
    authorization: object
    envelope: CommandEnvelope | None = None
    enqueue_deployment: object = None


def delivery_context(uow, actor, project_id, action, *, additional_user_ids=()):
    validate_actor(actor)
    if additional_user_ids:
        lock_current_subject(uow, actor, additional_user_ids=additional_user_ids)
    decision = authorize_current(uow, actor, AuthoritativeResource(project_id, "project", project_id), action)
    assert_schema_ready(uow.connection)
    return DeliveryContext(uow, actor, project_id, decision)


_REQUESTS = {
    CreateReleaseRequest: ("p1-release-create-r1", create_release),
    CreateEnvironmentRequest: ("p1-environment-create-r1", create_environment),
    CreateEnvironmentConfigRequest: ("p1-environment-config-create-r1", create_config),
    CreateDeploymentPlanRequest: ("p1-deployment-plan-create-r1", create_plan),
    ApproveDeploymentPlanRequest: ("p1-deployment-approve-r1", approve_plan),
}


def execute_delivery(uow, actor, project_id, request, *, idempotency_key, target_id=None, enqueue_deployment=None):
    if type(request) not in _REQUESTS:
        raise TaskBoundaryError("delivery_request_invalid", status_code=422)
    request = type(request).model_validate(request.model_dump(mode="python"))
    schema, apply = _REQUESTS[type(request)]
    approving = isinstance(request, ApproveDeploymentPlanRequest)
    context = delivery_context(uow, actor, project_id, "deployment.approve" if approving else "project.manage")
    resource = AuthoritativeResource(project_id, "project", project_id)
    intent = CommandIntent(request_schema_revision=schema, caller=actor.principal,
        scope=resource.scope, target=resource.target_scope, action=context.authorization.envelope.action,
        expected_resource_revision=0)
    context.envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=idempotency_key,
        request_digest=request_digest(intent, DeliveryCommandBody(target_id=target_id, request=request.model_dump(mode="json"))))
    context.enqueue_deployment = enqueue_deployment
    existing = lock_and_get(uow.connection, context.envelope)
    if existing is not None:
        return DeliveryHttpResult(status_code=existing.status_code, body=DeliveryCommandResult.model_validate(existing.result))
    try:
        with uow.connection.begin_nested():
            value = apply(context, request) if target_id is None else apply(context, target_id, request)
            operation_id = value.value.operation_id if approving else None
            result = DeliveryCommandResult(command_id=context.envelope.command_id, project_id=project_id,
                outcome="approved" if approving else "created", code="deployment_approved" if approving else "delivery_object_created",
                object_id=value.object_id, digest=value.digest, operation_id=operation_id)
            append_event(uow.connection, command_id=context.envelope.command_id, project_id=project_id,
                aggregate_kind="delivery", aggregate_id=value.object_id, aggregate_version=1,
                event_type="delivery." + result.outcome, schema_version="p1-delivery-event-r1", payload=result)
            status = 200 if approving else 201
    except ComposeParseError:
        result = DeliveryCommandResult(command_id=context.envelope.command_id, project_id=project_id,
            outcome="rejected", code="deployment_configuration_invalid")
        status = 422
    except TaskBoundaryError as error:
        if error.status_code not in {409, 422}:
            raise
        result = DeliveryCommandResult(command_id=context.envelope.command_id, project_id=project_id,
            outcome="rejected", code=error.code)
        status = error.status_code
    save_result(uow.connection, context.envelope, result, status_code=status, authorization=context.authorization.envelope)
    return DeliveryHttpResult(status_code=status, body=result)


class DeliveryApplication:
    def __init__(self, engine, control_engine, *, enqueue_deployment):
        self.engine, self.control_engine, self.enqueue_deployment = engine, control_engine, enqueue_deployment

    def command(self, actor, project_id, request, *, idempotency_key, target_id=None):
        with UnitOfWork(self.engine) as uow:
            return execute_delivery(uow, actor, project_id, request, idempotency_key=idempotency_key,
                target_id=target_id, enqueue_deployment=self.enqueue_deployment)

    def query(self, actor, project_id, kind, object_id):
        with UnitOfWork(self.control_engine) as uow:
            delivery_context(uow, actor, project_id, "resource.read")
            if kind == "environment":
                row, value = lock_binding(uow.connection, project_id, object_id)
                from modules.delivery.release_recipe import delivery_digest
                from modules.delivery.target_facts import latest_observation

                observation = latest_observation(uow.connection, value)
                now = uow.connection.scalar(select(func.clock_timestamp()))
                state = "missing"
                if observation is not None:
                    state = "current" if observation.observed_at <= now < observation.observed_at + timedelta(seconds=60) else "stale"
                    if not observation.reconciled:
                        state = "unknown"
                return EnvironmentView(object_id=object_id, digest=delivery_digest(value), value=value,
                    environment_revision=row["environment_revision"], config_revision=row["config_revision"],
                    active_operation_id=row["active_operation_id"], observation=observation,
                    observation_state_digest=delivery_digest(observation.state) if observation else None,
                    observation_status=state)
            return read_object(uow.connection, project_id, kind, object_id)

    def deployment(self, actor, project_id, plan_id):
        with UnitOfWork(self.control_engine) as uow:
            delivery_context(uow, actor, project_id, "resource.read")
            plan = read_object(uow.connection, project_id, "plan", plan_id)
            row, _ = lock_binding(uow.connection, project_id, plan.value.binding.binding_id)
            exists = uow.connection.scalar(select(deployment_approvals.c.plan_id).where(deployment_approvals.c.plan_id == plan_id))
            approval = None if exists is None else read_object(uow.connection, project_id, "approval", plan_id).value
            status = "approval_pending" if approval is None else "awaiting_remote_agent"
            if approval is not None and row["active_operation_id"] == approval.operation_id:
                status = "execution_registered"
            if approval is not None:
                from modules.delivery.remote_store import step_results

                results = step_results(uow.connection, approval.operation_id)
                if any(value.status == "unknown" for value in results.values()):
                    status = "needs_reconciliation"
                elif any(value.status == "failed_known" for value in results.values()):
                    status = "failed_known"
                elif all(step.step_id in results and results[step.step_id].status == "succeeded" for step in plan.value.steps):
                    status = "succeeded"
            return DeploymentView(plan=plan, approval=approval, operation_id=approval.operation_id if approval else None,
                status=status, environment_revision=row["environment_revision"])

    def preflight(self, actor, project_id, plan_id, request):
        with UnitOfWork(self.control_engine) as uow:
            # Read locking metadata only; expose no object before current access.
            owner = uow.connection.scalar(select(deployment_approvals.c.value_json["approver_user_id"].astext).where(
                deployment_approvals.c.plan_id == plan_id, deployment_approvals.c.project_id == project_id))
            context = delivery_context(uow, actor, project_id, "deployment.approve",
                additional_user_ids=(owner,) if owner else ())
            return approved_preflight(context, plan_id, request.plan_digest)
