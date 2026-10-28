"""Archive delivery commands/queries; target receipts have no public writer."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p1.delivery_records import DeliveryObject, DeploymentPreflight, DeploymentView, EnvironmentView
from packages.contracts.p1.delivery_requests import (
    ApproveDeploymentPlanRequest, CheckDeploymentPlanRequest, CloseDeploymentRequest, CreateDeploymentPlanRequest,
    CreateEnvironmentConfigRequest, CreateEnvironmentRequest, CreateReleaseRequest, DeliveryCommandResult,
)
from .auth import get_runtime
from .requests import strict_body
from .routes_resources import ControlActor, IdempotencyKey, NormalActor

router = APIRouter(prefix="/api/projects/{project_id}", tags=["delivery"])


def _command(request, actor, project_id, body, idempotency_key, target_id=None):
    result = get_runtime(request).delivery.command(actor, project_id, body,
        idempotency_key=idempotency_key, target_id=target_id)
    return JSONResponse(status_code=result.status_code, content=result.body.model_dump(mode="json"))


@router.post("/releases", response_model=DeliveryCommandResult, status_code=201, name="delivery.release.create")
def create_release(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                   body: CreateReleaseRequest = Depends(strict_body(CreateReleaseRequest))):
    return _command(request, actor, project_id, body, idempotency_key)


@router.get("/releases/{release_id}", response_model=DeliveryObject, name="delivery.release.query")
def release(request: Request, project_id: Identifier, release_id: Identifier, actor: ControlActor):
    return get_runtime(request).delivery.query(actor, project_id, "release", release_id)


@router.post("/environments", response_model=DeliveryCommandResult, status_code=201, name="delivery.environment.create")
def create_environment(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                       body: CreateEnvironmentRequest = Depends(strict_body(CreateEnvironmentRequest))):
    return _command(request, actor, project_id, body, idempotency_key)


@router.get("/environments/{binding_id}", response_model=EnvironmentView, name="delivery.environment.query")
def environment(request: Request, project_id: Identifier, binding_id: Identifier, actor: ControlActor):
    return get_runtime(request).delivery.query(actor, project_id, "environment", binding_id)


@router.post("/environments/{binding_id}/configurations", response_model=DeliveryCommandResult, status_code=201,
             name="delivery.configuration.create")
def create_config(request: Request, project_id: Identifier, binding_id: Identifier, actor: NormalActor,
                  idempotency_key: IdempotencyKey,
                  body: CreateEnvironmentConfigRequest = Depends(strict_body(CreateEnvironmentConfigRequest))):
    return _command(request, actor, project_id, body, idempotency_key, binding_id)


@router.get("/environment-configurations/{config_id}", response_model=DeliveryObject, name="delivery.configuration.query")
def configuration(request: Request, project_id: Identifier, config_id: Identifier, actor: ControlActor):
    return get_runtime(request).delivery.query(actor, project_id, "configuration", config_id)


@router.post("/environments/{binding_id}/deployment-plans", response_model=DeliveryCommandResult, status_code=201,
             name="delivery.plan.create")
def create_plan(request: Request, project_id: Identifier, binding_id: Identifier, actor: NormalActor,
                idempotency_key: IdempotencyKey,
                body: CreateDeploymentPlanRequest = Depends(strict_body(CreateDeploymentPlanRequest))):
    return _command(request, actor, project_id, body, idempotency_key, binding_id)


@router.get("/deployment-plans/{plan_id}", response_model=DeploymentView, name="delivery.plan.query")
def plan(request: Request, project_id: Identifier, plan_id: Identifier, actor: ControlActor):
    return get_runtime(request).delivery.deployment(actor, project_id, plan_id)


@router.post("/deployment-plans/{plan_id}/approvals", response_model=DeliveryCommandResult, name="delivery.plan.approve")
def approve(request: Request, project_id: Identifier, plan_id: Identifier, actor: NormalActor,
            idempotency_key: IdempotencyKey,
            body: ApproveDeploymentPlanRequest = Depends(strict_body(ApproveDeploymentPlanRequest))):
    return _command(request, actor, project_id, body, idempotency_key, plan_id)


@router.post("/deployment-plans/{plan_id}/preflight", response_model=DeploymentPreflight, name="delivery.plan.preflight")
def preflight(request: Request, project_id: Identifier, plan_id: Identifier, actor: ControlActor,
              body: CheckDeploymentPlanRequest = Depends(strict_body(CheckDeploymentPlanRequest))):
    return get_runtime(request).delivery.preflight(actor, project_id, plan_id, body)


@router.post("/deployment-plans/{plan_id}/closeout", response_model=DeliveryCommandResult, name="delivery.plan.closeout")
def closeout(request: Request, project_id: Identifier, plan_id: Identifier, actor: ControlActor,
             idempotency_key: IdempotencyKey,
             body: CloseDeploymentRequest = Depends(strict_body(CloseDeploymentRequest))):
    return _command(request, actor, project_id, body, idempotency_key, plan_id)
