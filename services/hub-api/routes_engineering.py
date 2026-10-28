"""Authenticated engineering intents and observations; no physical work in HTTP."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from starlette.responses import JSONResponse

from modules.identity.actors import AuthenticatedActor
from modules.workspaces.queries import WorkspaceOperationView
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p1.build_records import BuildView
from packages.contracts.p1.build_requests import BuildCommandResult, RequestBuildRequest
from packages.contracts.p1.reference_requests import CreateReferenceTaskRequest, ReferenceTaskResult
from packages.contracts.p1.source_requests import (
    ImportReferenceSourceRequest, SourceImportCommandResult, SourceImportView,
)
from packages.contracts.p1.workspace_records import PhysicalCandidateRecord
from packages.contracts.p1.workspace_uploads import WorkspaceMutationUpload
from packages.contracts.p1.workspace_requests import (
    CreateWorkspaceRequest, MaterializeWorkspaceRequest, SubmitWorkspaceCandidateRequest,
    WorkspaceCommandResult, WorkspaceView,
)
from packages.contracts.p2.candidates import FixCandidateCommandResult, FixCandidateRequest, FixedCandidateView
from .auth import control_actor, get_runtime, normal_actor
from .contracts import ApiErrorResponse
from .errors import ApiRequestError
from .requests import strict_body
from .workspace_ingress import accept_uploaded_mutation

router = APIRouter(prefix="/api", tags=["engineering"])
NormalActor = Annotated[AuthenticatedActor, Depends(normal_actor)]
ControlActor = Annotated[AuthenticatedActor, Depends(control_actor)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


def _response(result):
    return JSONResponse(status_code=result.status_code, content=result.body.model_dump(mode="json"))


def _command_errors(model):
    return {status: {"model": model | ApiErrorResponse} for status in (409, 422)}


@router.post("/projects/{project_id}/source-imports", response_model=SourceImportCommandResult, status_code=202,
             responses=_command_errors(SourceImportCommandResult))
def import_source(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                  body: ImportReferenceSourceRequest = Depends(strict_body(ImportReferenceSourceRequest))):
    return _response(get_runtime(request).sources.import_reference(actor, project_id, body,
                                                                  idempotency_key=idempotency_key))


@router.get("/projects/{project_id}/source-imports/{operation_id}", response_model=SourceImportView)
def source_status(request: Request, project_id: Identifier, operation_id: Identifier, actor: ControlActor):
    return get_runtime(request).sources.query(actor, project_id, operation_id)


@router.post("/projects/{project_id}/reference-tasks", response_model=ReferenceTaskResult, status_code=201)
def reference_task(request: Request, project_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                   body: CreateReferenceTaskRequest = Depends(strict_body(CreateReferenceTaskRequest))):
    runtime = get_runtime(request)
    source = runtime.sources.query(actor, project_id, body.source_operation_id)
    if source.registration is None:
        raise ApiRequestError("source_import_not_registered", 409)
    result = runtime.reference_tasks.create(
        actor, project_id, source.registration, expected_project_revision=body.expected_project_revision,
        idempotency_key=idempotency_key, title=body.title, goal=body.goal, budget=body.budget,
    )
    return ReferenceTaskResult(task=result.bound.body, input_set_ref=result.inputs.input_set_ref)


@router.post("/tasks/{task_id}/workspaces", response_model=WorkspaceCommandResult, status_code=201,
             responses=_command_errors(WorkspaceCommandResult))
def create_workspace(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                     body: CreateWorkspaceRequest = Depends(strict_body(CreateWorkspaceRequest))):
    return _response(get_runtime(request).workspaces.create(actor, task_id, body, idempotency_key=idempotency_key))


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceView)
def workspace_status(request: Request, workspace_id: Identifier, actor: ControlActor):
    return get_runtime(request).workspaces.query(actor, workspace_id)


@router.post("/workspaces/{workspace_id}/materialize", response_model=WorkspaceCommandResult, status_code=202,
             responses=_command_errors(WorkspaceCommandResult))
def materialize_workspace(request: Request, workspace_id: Identifier, actor: NormalActor,
                          idempotency_key: IdempotencyKey,
                          body: MaterializeWorkspaceRequest = Depends(strict_body(MaterializeWorkspaceRequest))):
    return _response(get_runtime(request).workspaces.materialize(actor, workspace_id, body,
                                                                idempotency_key=idempotency_key))


@router.post("/workspaces/{workspace_id}/candidates", response_model=WorkspaceCommandResult, status_code=202,
             responses=_command_errors(WorkspaceCommandResult))
def submit_candidate(request: Request, workspace_id: Identifier, actor: NormalActor,
                     idempotency_key: IdempotencyKey,
                     body: SubmitWorkspaceCandidateRequest = Depends(strict_body(SubmitWorkspaceCandidateRequest))):
    return _response(get_runtime(request).workspaces.submit_candidate(actor, workspace_id, body,
                                                                     idempotency_key=idempotency_key))


@router.post("/workspaces/{workspace_id}/files", response_model=WorkspaceCommandResult, status_code=202,
             responses=_command_errors(WorkspaceCommandResult))
def mutate_file(request: Request, workspace_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                body: WorkspaceMutationUpload = Depends(strict_body(WorkspaceMutationUpload))):
    return _response(accept_uploaded_mutation(get_runtime(request).workspaces, actor, workspace_id, body,
                                             idempotency_key=idempotency_key))


@router.get("/workspaces/{workspace_id}/operations/{operation_id}", response_model=WorkspaceOperationView)
def workspace_operation(request: Request, workspace_id: Identifier, operation_id: Identifier, actor: ControlActor):
    return get_runtime(request).workspaces.query_operation(actor, workspace_id, operation_id)


@router.get("/workspaces/{workspace_id}/candidates/{candidate_id}", response_model=PhysicalCandidateRecord)
def candidate_status(request: Request, workspace_id: Identifier, candidate_id: Identifier, actor: ControlActor):
    return get_runtime(request).workspaces.query_candidate(actor, workspace_id, candidate_id)


@router.post("/tasks/{task_id}/builds", response_model=BuildCommandResult, status_code=202,
             responses=_command_errors(BuildCommandResult))
def request_build(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                  body: RequestBuildRequest = Depends(strict_body(RequestBuildRequest))):
    return _response(get_runtime(request).builds.request(actor, task_id, body, idempotency_key=idempotency_key))


@router.get("/tasks/{task_id}/builds/{operation_id}", response_model=BuildView)
def build_status(request: Request, task_id: Identifier, operation_id: Identifier, actor: ControlActor):
    return get_runtime(request).builds.query(actor, task_id, operation_id)


@router.post("/tasks/{task_id}/candidates", response_model=FixCandidateCommandResult, status_code=201,
             responses=_command_errors(FixCandidateCommandResult))
def fix_candidate(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                  body: FixCandidateRequest = Depends(strict_body(FixCandidateRequest))):
    return _response(get_runtime(request).candidates.fix(actor, task_id, body, idempotency_key=idempotency_key))


@router.get("/tasks/{task_id}/candidates/{candidate_id}", response_model=FixedCandidateView)
def fixed_candidate_status(request: Request, task_id: Identifier, candidate_id: Identifier, actor: ControlActor):
    return get_runtime(request).candidates.query(actor, task_id, candidate_id)
