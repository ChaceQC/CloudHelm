"""Project queue commands expose fixed identities, never raw Git operations."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from modules.identity.actors import AuthenticatedActor
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p2.merge_queue import (
    AdvanceMergeRequest, EnqueueMergeRequest, IntegrationReview, MergeQueueEntry, MergeQueueView, ReviewMergeRequest,
)
from .auth import control_actor, get_runtime, normal_actor
from .requests import strict_body

router = APIRouter(prefix="/api", tags=["integration"])
NormalActor = Annotated[AuthenticatedActor, Depends(normal_actor)]
ControlActor = Annotated[AuthenticatedActor, Depends(control_actor)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


@router.post("/tasks/{task_id}/merge-queue", response_model=MergeQueueEntry, status_code=202)
def enqueue(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
            body: EnqueueMergeRequest = Depends(strict_body(EnqueueMergeRequest))):
    return get_runtime(request).merges.enqueue(actor, task_id, body, idempotency_key=idempotency_key)


@router.get("/projects/{project_id}/merge-queue", response_model=tuple[MergeQueueEntry, ...])
def queue(request: Request, project_id: Identifier, actor: ControlActor):
    return get_runtime(request).merges.list(actor, project_id)


@router.get("/merge-queue/{entry_id}", response_model=MergeQueueView)
def status(request: Request, entry_id: Identifier, actor: ControlActor):
    return get_runtime(request).merges.query(actor, entry_id)


@router.post("/merge-queue/{entry_id}/review", response_model=IntegrationReview, status_code=201)
def review(request: Request, entry_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
           body: ReviewMergeRequest = Depends(strict_body(ReviewMergeRequest))):
    return get_runtime(request).merges.review(actor, entry_id, body, idempotency_key=idempotency_key)


@router.post("/merge-queue/{entry_id}/advance", response_model=MergeQueueEntry, status_code=202)
def advance(request: Request, entry_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
            body: AdvanceMergeRequest = Depends(strict_body(AdvanceMergeRequest))):
    return get_runtime(request).merges.advance(actor, entry_id, body, idempotency_key=idempotency_key)
