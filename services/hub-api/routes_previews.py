"""Human decisions and preview lifecycle use the existing authenticated command boundary."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import task_resource
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.integration.candidates import _read
from modules.integration.merge_validity import require_merged_report
from modules.integration.validity import selected_verification
from modules.workspaces.preview_access import _environment
from modules.workspaces.preview_profiles import fixed_preview_inputs
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p2.human_tests import (
    HumanTestCommandResult, HumanTestConclusionRequest, HumanTestSession, HumanTestSessionGuard, StartHumanTestRequest,
)
from packages.contracts.p2.preview_environments import (
    AttachDevelopmentPreviewRequest, HumanTestOption, HumanTestOptions, PreviewEnvironmentResult,
    PreviewEnvironmentControlRequest, PreviewEnvironmentView, StartCandidatePreviewRequest,
)
from packages.contracts.p2.previews import PreviewAccessRequest, PreviewAuthorizationRecord
from .auth import control_actor, get_runtime, normal_actor
from .requests import strict_body

router = APIRouter(prefix="/api", tags=["previews"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]
Normal = Annotated[object, Depends(normal_actor)]
Control = Annotated[object, Depends(control_actor)]


@router.get("/tasks/{task_id}/human-tests", response_model=tuple[HumanTestSession, ...])
def human_tests(request: Request, task_id: Identifier, actor: Control):
    return get_runtime(request).human_tests.list(actor, task_id)


@router.get("/tasks/{task_id}/human-test-options", response_model=HumanTestOptions)
def human_options(request: Request, task_id: Identifier, actor: Control):
    runtime = get_runtime(request)
    with UnitOfWork(runtime.pools.control) as uow:
        task, _ = lock_task_access(uow, actor, task_id, "resource.read")
        try:
            authorize_current(uow, actor, task_resource(task), "human_test.enter")
        except IdentityError as error:
            if error.code != "permission_denied":
                raise
            tester_id = None
        else:
            tester_id = actor.principal.subject_id
        selected = selected_verification(uow.connection, task)
        if selected is None or not selected.usable:
            return HumanTestOptions(tester_id=tester_id)
        try:
            require_merged_report(uow.connection, task, selected)
            candidate = _read(uow.connection, task, selected.report.candidate_id)
            config, dataset = fixed_preview_inputs(uow.connection, candidate)
        except TaskBoundaryError as error:
            if error.code not in {"project_integration_required", "project_integration_not_accepted",
                                  "integration_attempt_not_current", "integration_final_candidate_required",
                                  "integration_final_evidence_required", "verification_not_applicable",
                                  "preview_profile_not_supported"}:
                raise
            return HumanTestOptions(tester_id=tester_id)
        option = HumanTestOption(candidate_id=candidate.candidate_id, label=candidate.candidate_id,
                                test_config_ref=config, dataset_ref=dataset)
        return HumanTestOptions(candidates=(option,), tester_id=tester_id)


@router.post("/tasks/{task_id}/human-tests", response_model=HumanTestCommandResult, status_code=202)
def start_human(request: Request, task_id: Identifier, actor: Normal, idempotency_key: Key,
                body: StartHumanTestRequest = Depends(strict_body(StartHumanTestRequest))):
    return get_runtime(request).human_tests.start(actor, task_id, body, idempotency_key=idempotency_key)


@router.get("/human-tests/{session_id}", response_model=HumanTestSession)
def human_session(request: Request, session_id: Identifier, actor: Control):
    return get_runtime(request).human_tests.query(actor, session_id)


@router.post("/human-tests/{session_id}/ready", response_model=HumanTestCommandResult)
def human_ready(request: Request, session_id: Identifier, actor: Normal, idempotency_key: Key,
                body: HumanTestSessionGuard = Depends(strict_body(HumanTestSessionGuard))):
    return get_runtime(request).human_tests.mark_ready(actor, session_id, body, idempotency_key=idempotency_key)


@router.post("/human-tests/{session_id}/conclusion", response_model=HumanTestCommandResult)
def human_conclusion(request: Request, session_id: Identifier, actor: Normal, idempotency_key: Key,
                     body: HumanTestConclusionRequest = Depends(strict_body(HumanTestConclusionRequest))):
    return get_runtime(request).human_tests.conclude(actor, session_id, body, idempotency_key=idempotency_key)


def _human_control(action):
    def control(request: Request, session_id: Identifier, actor: Normal, idempotency_key: Key,
                body: HumanTestSessionGuard = Depends(strict_body(HumanTestSessionGuard))):
        return get_runtime(request).human_tests.control(actor, session_id, body, action, idempotency_key=idempotency_key)
    return control


for path, action in (("activity", "activity"), ("renew", "renew"), ("yield", "give_up"), ("cancel", "cancel")):
    router.add_api_route("/human-tests/{session_id}/" + path, _human_control(action), methods=["POST"],
                         response_model=HumanTestCommandResult, name="human_test." + action)


@router.post("/tasks/{task_id}/candidate-previews", response_model=PreviewEnvironmentResult, status_code=202)
def candidate_preview(request: Request, task_id: Identifier, actor: Normal, idempotency_key: Key,
                      body: StartCandidatePreviewRequest = Depends(strict_body(StartCandidatePreviewRequest))):
    return get_runtime(request).preview_environments.start(actor, task_id, body, idempotency_key=idempotency_key)


@router.post("/tasks/{task_id}/development-previews", response_model=PreviewEnvironmentResult, status_code=202)
def development_preview(request: Request, task_id: Identifier, actor: Normal, idempotency_key: Key,
                        body: AttachDevelopmentPreviewRequest = Depends(strict_body(AttachDevelopmentPreviewRequest))):
    return get_runtime(request).preview_environments.start(actor, task_id, body,
                                                           idempotency_key=idempotency_key, development=True)


@router.get("/preview-environments/{environment_id}", response_model=PreviewEnvironmentView)
def preview_environment(request: Request, environment_id: Identifier, actor: Control, for_open: bool = False):
    return get_runtime(request).preview_environments.query(actor, environment_id, for_open=for_open)


@router.post("/preview-environments/{environment_id}/stop", response_model=PreviewEnvironmentResult, status_code=202)
def stop_preview(request: Request, environment_id: Identifier, actor: Normal, idempotency_key: Key,
                 body: PreviewEnvironmentControlRequest = Depends(strict_body(PreviewEnvironmentControlRequest))):
    return get_runtime(request).preview_environments.stop(actor, environment_id, body, idempotency_key=idempotency_key)


@router.get("/preview-environments/{environment_id}/access-request", response_model=PreviewAccessRequest)
def access_parameters(request: Request, environment_id: Identifier, actor: Control):
    runtime = get_runtime(request)
    with UnitOfWork(runtime.pools.control) as uow:
        initial = _environment(uow.connection, environment_id)
        task, _ = lock_task_access(uow, actor, initial.task_id, "resource.read")
        environment = runtime.preview_environments.refresh_in_uow(uow, environment_id)
        return PreviewAccessRequest(expected_version=task["version"], expected_control_revision=task["control_revision"],
            expected_input_validity_revision=task["input_validity_revision"],
            expected_environment_revision=environment.revision, expires_at=environment.expires_at)


@router.post("/preview-environments/{environment_id}/access")
def preview_access(request: Request, environment_id: Identifier, actor: Normal, idempotency_key: Key,
                   body: PreviewAccessRequest = Depends(strict_body(PreviewAccessRequest))):
    # This protected response belongs only to the trusted management document.
    runtime = get_runtime(request)
    result = runtime.previews.issue(actor, environment_id, body, idempotency_key, request.headers.get("origin", ""))
    return JSONResponse({"authorization": result.authorization.model_dump(mode="json"),
                         "ticket": result.ticket.get_secret_value() if result.ticket else None},
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/preview-authorizations/{authorization_id}", response_model=PreviewAuthorizationRecord)
def preview_authorization(request: Request, authorization_id: Identifier, actor: Control):
    return get_runtime(request).previews.query(actor, authorization_id)


@router.post("/preview-authorizations/{authorization_id}/revoke", response_model=PreviewAuthorizationRecord)
def revoke(request: Request, authorization_id: Identifier, actor: Normal, idempotency_key: Key):
    return get_runtime(request).previews.revoke(actor, authorization_id, idempotency_key)
