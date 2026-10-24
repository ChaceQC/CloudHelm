"""Resource intents and observations; no public process, receipt or host-path input."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from modules.identity.actors import AuthenticatedActor
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p0.resource_contracts import ResourceAdjustment, ResourceAllocation
from packages.contracts.p1.resource_protocol import ReservationResult, ReserveResourcesRequest, ResourceAdjustmentResult
from .auth import control_actor, get_runtime, normal_actor
from .requests import strict_body
from .contracts import ApiErrorResponse

router = APIRouter(tags=["resources"])
NormalActor = Annotated[AuthenticatedActor, Depends(normal_actor)]
ControlActor = Annotated[AuthenticatedActor, Depends(control_actor)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


@router.post("/api/tasks/{task_id}/resource-reservations", response_model=ReservationResult,
             status_code=202, name="resources.reserve")
def reserve(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
            body: ReserveResourcesRequest = Depends(strict_body(ReserveResourcesRequest))):
    return get_runtime(request).resources.reserve(actor, task_id, body, idempotency_key=idempotency_key)


@router.get("/api/resource-reservations/{reservation_id}", response_model=ResourceAllocation,
            name="resources.query")
def query(request: Request, reservation_id: Identifier, actor: ControlActor):
    return get_runtime(request).resources.query(actor, reservation_id)


@router.post("/api/resource-reservations/{reservation_id}/adjustments", response_model=ResourceAdjustmentResult,
             name="resources.adjust", responses={409: {"model": ResourceAdjustmentResult | ApiErrorResponse}})
def adjust(request: Request, reservation_id: Identifier, actor: NormalActor,
           body: ResourceAdjustment = Depends(strict_body(ResourceAdjustment))):
    result = get_runtime(request).resources.adjust(actor, reservation_id, body)
    return JSONResponse(status_code=409 if result.status == "rejected" else 200,
                        content=result.model_dump(mode="json"))
