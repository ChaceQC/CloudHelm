"""Existing project reads and management; creation remains a maintenance operation."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import JSONResponse

from database.uow import UnitOfWork
from modules.identity.actors import AuthenticatedActor
from modules.identity.grants import list_project_roles
from modules.projects.queries import get_project, list_projects
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p1.identity_contracts import ProjectPage, ProjectView, RoleBindingPage
from packages.contracts.p1.identity_requests import GrantProjectRoleRequest, RenameProjectRequest, RevokeProjectRoleRequest
from packages.contracts.p1.identity_results import ProjectCommandResult
from .auth import control_actor, get_runtime, normal_actor
from .contracts import ApiErrorResponse
from .requests import strict_body

router = APIRouter(prefix="/api/projects", tags=["projects"])
NormalActor = Annotated[AuthenticatedActor, Depends(normal_actor)]
ControlActor = Annotated[AuthenticatedActor, Depends(control_actor)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


@router.get("", response_model=ProjectPage, name="projects.list")
def project_list(request: Request, actor: ControlActor, after: Identifier | None = None,
                 limit: Annotated[int, Query(ge=1, le=100)] = 50):
    with UnitOfWork(get_runtime(request).pools.control) as uow:
        return list_projects(uow, actor, after=after, limit=limit)


@router.get("/{project_id}", response_model=ProjectView, name="projects.get")
def project_get(request: Request, project_id: Identifier, actor: ControlActor):
    with UnitOfWork(get_runtime(request).pools.control) as uow:
        return get_project(uow, actor, project_id)


@router.get("/{project_id}/role-bindings", response_model=RoleBindingPage, name="projects.roles")
def project_roles(request: Request, project_id: Identifier, actor: ControlActor,
                  after: Identifier | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    with UnitOfWork(get_runtime(request).pools.control) as uow:
        return list_project_roles(uow, actor, project_id, after=after, limit=limit)


@router.patch("/{project_id}", response_model=ProjectCommandResult, name="projects.rename",
              responses={409: {"model": ProjectCommandResult | ApiErrorResponse}})
def project_rename(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                   body: RenameProjectRequest = Depends(strict_body(RenameProjectRequest))):
    result = get_runtime(request).projects.rename(actor, project_id, body, idempotency_key=idempotency_key)
    return JSONResponse(status_code=result.status_code, content=result.body.model_dump(mode="json"))


@router.post("/{project_id}/role-bindings", response_model=ProjectCommandResult, name="projects.grant_role",
             responses={409: {"model": ProjectCommandResult | ApiErrorResponse}})
def project_grant(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                  body: GrantProjectRoleRequest = Depends(strict_body(GrantProjectRoleRequest))):
    result = get_runtime(request).projects.grant_role(actor, project_id, body, idempotency_key=idempotency_key)
    return JSONResponse(status_code=result.status_code, content=result.body.model_dump(mode="json"))


@router.post("/{project_id}/role-bindings/revoke", response_model=ProjectCommandResult, name="projects.revoke_role",
             responses={409: {"model": ProjectCommandResult | ApiErrorResponse}})
def project_revoke(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                   body: RevokeProjectRoleRequest = Depends(strict_body(RevokeProjectRoleRequest))):
    result = get_runtime(request).projects.revoke_role(actor, project_id, body, idempotency_key=idempotency_key)
    return JSONResponse(status_code=result.status_code, content=result.body.model_dump(mode="json"))
