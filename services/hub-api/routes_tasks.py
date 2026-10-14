"""Task HTTP adapter; the domain application owns every command and control rule."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from starlette.responses import JSONResponse

from modules.identity.actors import AuthenticatedActor
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p0.task_control_contracts import TaskCompletionReport
from packages.contracts.p1.task_requests import (
    CancelTaskRequest, CompleteTaskRequest, CreateTaskRequest, ReconcileTaskRequest, StartTaskRequest,
)
from packages.contracts.p1.task_results import TaskCommandResult, TaskCreateRejection, TaskView
from .auth import control_actor, get_runtime, normal_actor
from .contracts import ApiErrorResponse
from .requests import strict_body

router = APIRouter(tags=["tasks"])
NormalActor = Annotated[AuthenticatedActor, Depends(normal_actor)]
ControlActor = Annotated[AuthenticatedActor, Depends(control_actor)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]
_COMMAND_RESPONSES = {
    **{code: {"model": TaskCommandResult} for code in (200, 201, 202)},
    **{code: {"model": TaskCommandResult | ApiErrorResponse} for code in (403, 404, 409, 422)},
}
_CREATE_RESPONSES = {
    **_COMMAND_RESPONSES,
    **{code: {"model": TaskCreateRejection | ApiErrorResponse} for code in (403, 404, 409, 422)},
}


def _result(result):
    return JSONResponse(status_code=result.status_code, content=result.body.model_dump(mode="json"))


@router.post("/api/projects/{project_id}/tasks", response_model=TaskCommandResult, status_code=201,
             responses=_CREATE_RESPONSES, name="tasks.create")
def task_create(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                body: CreateTaskRequest = Depends(strict_body(CreateTaskRequest))):
    return _result(get_runtime(request).tasks.create(actor, project_id, body, idempotency_key=idempotency_key))


@router.get("/api/tasks/{task_id}", response_model=TaskView, name="tasks.query")
def task_query(request: Request, task_id: Identifier, actor: ControlActor):
    return get_runtime(request).tasks.query(actor, task_id)


@router.get("/api/tasks/{task_id}/completion-report", response_model=TaskCompletionReport, name="tasks.report")
def task_report(request: Request, task_id: Identifier, actor: ControlActor):
    return get_runtime(request).tasks.report(actor, task_id)


@router.post("/api/tasks/{task_id}/start", response_model=TaskCommandResult, status_code=202,
             responses=_COMMAND_RESPONSES, name="tasks.start")
def task_start(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
               body: StartTaskRequest = Depends(strict_body(StartTaskRequest))):
    return _result(get_runtime(request).tasks.start(actor, task_id, body, idempotency_key=idempotency_key))


@router.post("/api/tasks/{task_id}/complete", response_model=TaskCommandResult,
             responses=_COMMAND_RESPONSES, name="tasks.complete")
def task_complete(request: Request, task_id: Identifier, actor: ControlActor, idempotency_key: IdempotencyKey,
                  body: CompleteTaskRequest = Depends(strict_body(CompleteTaskRequest))):
    return _result(get_runtime(request).tasks.complete(actor, task_id, body, idempotency_key=idempotency_key))


@router.post("/api/tasks/{task_id}/cancel", response_model=TaskCommandResult, status_code=202,
             responses=_COMMAND_RESPONSES, name="tasks.cancel")
def task_cancel(request: Request, task_id: Identifier, actor: ControlActor, idempotency_key: IdempotencyKey,
                body: CancelTaskRequest = Depends(strict_body(CancelTaskRequest))):
    return _result(get_runtime(request).tasks.cancel(actor, task_id, body, idempotency_key=idempotency_key))


@router.post("/api/tasks/{task_id}/reconcile", response_model=TaskCommandResult,
             responses=_COMMAND_RESPONSES, name="tasks.reconcile")
def task_reconcile(request: Request, task_id: Identifier, actor: ControlActor, idempotency_key: IdempotencyKey,
                   body: ReconcileTaskRequest = Depends(strict_body(ReconcileTaskRequest))):
    return _result(get_runtime(request).tasks.reconcile(actor, task_id, body, idempotency_key=idempotency_key))
