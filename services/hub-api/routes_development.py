"""Authenticated intents and projections for mutable Workspace environments."""

from fastapi import APIRouter, Depends, Request

from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p1.workspace_development_requests import (
    DisposeWorkspaceDevelopmentRequest, PrepareWorkspaceDevelopmentRequest,
    ResetWorkspaceDevelopmentDataRequest, ResumeWorkspaceDevelopmentRequest,
    SuspendWorkspaceDevelopmentRequest, WorkspaceDevelopmentCommandResult,
    WorkspaceDevelopmentEnvironmentView, WorkspaceDevelopmentOperationView,
)
from .auth import get_runtime
from .requests import strict_body
from .routes_engineering import ControlActor, IdempotencyKey, NormalActor, _command_errors, _response

router = APIRouter(prefix="/api", tags=["workspace development"])


@router.post("/workspaces/{workspace_id}/development-environments",
             response_model=WorkspaceDevelopmentCommandResult, status_code=202,
             responses=_command_errors(WorkspaceDevelopmentCommandResult))
def prepare(request: Request, workspace_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
            body: PrepareWorkspaceDevelopmentRequest = Depends(strict_body(PrepareWorkspaceDevelopmentRequest))):
    return _response(get_runtime(request).development.prepare(actor, workspace_id, body, key=idempotency_key))


@router.get("/development-environments/{environment_id}", response_model=WorkspaceDevelopmentEnvironmentView)
def environment(request: Request, environment_id: Identifier, actor: ControlActor):
    return get_runtime(request).development.query(actor, environment_id)


@router.get("/development-environments/{environment_id}/operations/{operation_id}",
            response_model=WorkspaceDevelopmentOperationView)
def operation(request: Request, environment_id: Identifier, operation_id: Identifier, actor: ControlActor):
    return get_runtime(request).development.query_operation(actor, environment_id, operation_id)


@router.post("/development-environments/{environment_id}/suspend",
             response_model=WorkspaceDevelopmentCommandResult, status_code=202,
             responses=_command_errors(WorkspaceDevelopmentCommandResult))
def suspend(request: Request, environment_id: Identifier, actor: ControlActor, idempotency_key: IdempotencyKey,
            body: SuspendWorkspaceDevelopmentRequest = Depends(strict_body(SuspendWorkspaceDevelopmentRequest))):
    return _response(get_runtime(request).development.control(actor, environment_id, body, key=idempotency_key))


@router.post("/development-environments/{environment_id}/resume",
             response_model=WorkspaceDevelopmentCommandResult, status_code=202,
             responses=_command_errors(WorkspaceDevelopmentCommandResult))
def resume(request: Request, environment_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
           body: ResumeWorkspaceDevelopmentRequest = Depends(strict_body(ResumeWorkspaceDevelopmentRequest))):
    return _response(get_runtime(request).development.control(actor, environment_id, body, key=idempotency_key))


@router.post("/development-environments/{environment_id}/reset-data",
             response_model=WorkspaceDevelopmentCommandResult, status_code=202,
             responses=_command_errors(WorkspaceDevelopmentCommandResult))
def reset_data(request: Request, environment_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
               body: ResetWorkspaceDevelopmentDataRequest = Depends(strict_body(ResetWorkspaceDevelopmentDataRequest))):
    return _response(get_runtime(request).development.control(actor, environment_id, body, key=idempotency_key))


@router.post("/development-environments/{environment_id}/dispose",
             response_model=WorkspaceDevelopmentCommandResult, status_code=202,
             responses=_command_errors(WorkspaceDevelopmentCommandResult))
def dispose(request: Request, environment_id: Identifier, actor: ControlActor, idempotency_key: IdempotencyKey,
            body: DisposeWorkspaceDevelopmentRequest = Depends(strict_body(DisposeWorkspaceDevelopmentRequest))):
    return _response(get_runtime(request).development.control(actor, environment_id, body, key=idempotency_key))
