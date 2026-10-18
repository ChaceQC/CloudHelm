"""Bounded helpers for the real mutable Workspace development method."""

from __future__ import annotations

import time

from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.source_requests import SourceImportCommandResult
from packages.contracts.p1.task_results import TaskView
from packages.contracts.p1.workspace_git import WorkspaceFile, content_digest
from packages.contracts.p1.workspace_requests import (
    MutateWorkspaceFileRequest,
    SubmitWorkspaceCandidateRequest,
    WorkspaceCommandResult,
    WorkspaceView,
)
from packages.contracts.p1.workspace_records import PhysicalCandidateRecord
from packages.contracts.p1.workspace_development_requests import (
    DisposeWorkspaceDevelopmentRequest,
    PrepareWorkspaceDevelopmentRequest,
    ResetWorkspaceDevelopmentDataRequest,
    ResumeWorkspaceDevelopmentRequest,
    SuspendWorkspaceDevelopmentRequest,
    WorkspaceDevelopmentCommandResult,
    WorkspaceDevelopmentEnvironmentView,
    WorkspaceDevelopmentOperationView,
)
from modules.workspaces.reference_seed import REFERENCE_PREFIX, _manifest, _seed_root
from modules.workspaces.safe_paths import read_regular
from scripts.p1.engineering_chain import operation
from scripts.p1.engineering_fixture import ROOT, require

WORKSPACE_METHOD_REVISION = "p1-2-workspace-development-r1"
DEV_MARKER_R1 = "cloudhelm-workspace-dev-marker-r1"
DEV_MARKER_R2 = "cloudhelm-workspace-dev-marker-r2"
DEV_MARKER_PATH = "backend/app/main.py"
LOCK_PATH = "backend/uv.lock"
DEVELOPMENT_DATA_R2 = "reference-synthetic-r2"
MAX_SOURCE_FILE_BYTES = 16 * 1024 * 1024

_CONTROL_TYPES = {
    "suspend": SuspendWorkspaceDevelopmentRequest,
    "resume": ResumeWorkspaceDevelopmentRequest,
    "reset_data": ResetWorkspaceDevelopmentDataRequest,
    "dispose": DisposeWorkspaceDevelopmentRequest,
}
_CONTROL_PATHS = {
    "suspend": "suspend",
    "resume": "resume",
    "reset_data": "reset-data",
    "dispose": "dispose",
}


class WorkspaceDevelopmentCheckFailure(AssertionError):
    """Fixed method failures only; never carry source, HTTP or Docker output."""


def fixed_reference_file(relative_path: str) -> bytes:
    """Read one fixed reference byte sequence and cross-check its frozen manifest."""
    relative_path = "backend/" + relative_path
    with _seed_root(ROOT) as root:
        expected = _manifest(root)
        data = read_regular(root, REFERENCE_PREFIX + "/" + relative_path, MAX_SOURCE_FILE_BYTES)
    require(relative_path in expected and content_digest(data) == "sha256:" + expected[relative_path],
            "workspace_development_fixed_reference_file_changed")
    return data


def workspace_file(path: str, data: bytes, *, mode: str = "100644") -> WorkspaceFile:
    return WorkspaceFile(path=path, mode=mode, size_bytes=len(data), content_digest=content_digest(data))


def initial_devmarker_source(base: bytes) -> bytes:
    require(b"/devmarker" not in base, "workspace_development_reference_already_has_devmarker")
    suffix = (
        "\n\n@app.get(\"/devmarker\")\n"
        "def workspace_development_marker() -> dict[str, str]:\n"
        f"    return {{\"marker\": \"{DEV_MARKER_R1}\"}}\n"
    ).encode("utf-8")
    return base + suffix


def replace_devmarker_source(source: bytes) -> bytes:
    old, new = DEV_MARKER_R1.encode("ascii"), DEV_MARKER_R2.encode("ascii")
    require(source.count(old) == 1 and source.count(new) == 0,
            "workspace_development_devmarker_variant_invalid")
    return source.replace(old, new, 1)


def mutate_workspace_file(probe, workspace_id: str, input_ref: EngineeringRef, manifest_digest: str,
                          path: str, content: bytes, previous_file: WorkspaceFile):
    view = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    binding = view.workspace.binding
    replacement = workspace_file(path, content, mode=previous_file.mode)
    request = MutateWorkspaceFileRequest(
        expected_version=view.task_version,
        expected_control_revision=view.control_revision,
        expected_input_validity_revision=view.input_validity_revision,
        input_set_ref=input_ref,
        expected_workspace_revision=binding.workspace_revision,
        expected_write_generation=binding.write_generation,
        action="write",
        path=path,
        expected_manifest_digest=manifest_digest,
        expected_file=previous_file,
        replacement=replacement,
    )
    accepted = probe.post(
        f"/api/workspaces/{workspace_id}/files",
        {"request": request.model_dump(mode="json"), "content_utf8": content.decode("utf-8")},
        WorkspaceCommandResult,
        expected=202,
    )
    receipt = operation(probe, workspace_id, accepted)
    require(receipt.outcome == "applied" and receipt.before_manifest_digest == manifest_digest
            and receipt.after_manifest_digest != manifest_digest and receipt.after_file == replacement,
            "workspace_development_controlled_file_write_not_registered")
    return receipt.after_manifest_digest, receipt.after_file, receipt


def wait_development_operation(probe, accepted: WorkspaceDevelopmentCommandResult, expected: str,
                               *, timeout: float = 240.0) -> WorkspaceDevelopmentOperationView:
    require(accepted.outcome == "accepted" and accepted.operation_id is not None
            and accepted.environment_id is not None and accepted.request_digest is not None,
            "workspace_development_http_intent_not_accepted")
    workflow_id = probe.handoff(accepted)
    path = (f"/api/development-environments/{accepted.environment_id}"
            f"/operations/{accepted.operation_id}")
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = probe.get(path, WorkspaceDevelopmentOperationView)
        status = probe.workflow_status(workflow_id)
        if last.operation_state in {"succeeded", "failed"}:
            if status not in {"SUCCESS", None}:
                raise WorkspaceDevelopmentCheckFailure("workspace_development_worker_workflow_failed")
            require(last.operation_state == expected,
                    "workspace_development_operation_terminal_state_mismatch")
            return last
        if status in {"ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"}:
            raise WorkspaceDevelopmentCheckFailure("workspace_development_worker_workflow_failed")
        time.sleep(0.2)
    raise WorkspaceDevelopmentCheckFailure("workspace_development_operation_timeout")


def development_environment(probe, environment_id: str) -> WorkspaceDevelopmentEnvironmentView:
    return probe.get(f"/api/development-environments/{environment_id}", WorkspaceDevelopmentEnvironmentView)


def submit_prepare(probe, workspace_id: str, input_ref: EngineeringRef) -> WorkspaceDevelopmentCommandResult:
    workspace = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    binding = workspace.workspace.binding
    request = PrepareWorkspaceDevelopmentRequest(
        expected_version=workspace.task_version,
        expected_control_revision=workspace.control_revision,
        expected_input_validity_revision=workspace.input_validity_revision,
        input_set_ref=input_ref,
        expected_workspace_revision=binding.workspace_revision,
        expected_write_generation=binding.write_generation,
    )
    return probe.post(
        f"/api/workspaces/{workspace_id}/development-environments", request,
        WorkspaceDevelopmentCommandResult, expected=202,
    )


def submit_control(probe, workspace_id: str, environment_id: str, input_ref: EngineeringRef,
                   action: str, *, target_data_revision: str | None = None, expected_status: int = 202
                   ) -> WorkspaceDevelopmentCommandResult:
    model = _CONTROL_TYPES.get(action)
    route = _CONTROL_PATHS.get(action)
    require(model is not None and route is not None, "workspace_development_control_action_invalid")
    workspace = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    environment = development_environment(probe, environment_id)
    observation = environment.latest_observation
    require(observation is not None and observation.state == environment.state,
            "workspace_development_control_observation_missing")
    binding = workspace.workspace.binding
    fields = dict(
        expected_version=workspace.task_version,
        expected_control_revision=workspace.control_revision,
        expected_input_validity_revision=workspace.input_validity_revision,
        input_set_ref=input_ref,
        expected_workspace_revision=binding.workspace_revision,
        expected_write_generation=binding.write_generation,
        expected_environment_revision=environment.environment_revision,
        expected_data_revision=observation.data_revision,
        expected_data_generation=observation.data_generation,
    )
    if action == "reset_data":
        require(target_data_revision is not None, "workspace_development_reset_revision_required")
        fields["target_data_revision"] = target_data_revision
    request = model(**fields)
    return probe.post(
        f"/api/development-environments/{environment_id}/{route}", request,
        WorkspaceDevelopmentCommandResult, expected=expected_status,
    )


def task_view(probe, task_id: str) -> TaskView:
    return probe.get(f"/api/tasks/{task_id}", TaskView)


def candidate_view(probe, workspace_id: str, candidate_id: str) -> PhysicalCandidateRecord:
    return probe.get(f"/api/workspaces/{workspace_id}/candidates/{candidate_id}", PhysicalCandidateRecord)


def freeze_workspace_candidate(probe, workspace_id: str, input_ref: EngineeringRef, manifest_digest: str):
    workspace = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    binding = workspace.workspace.binding
    request = SubmitWorkspaceCandidateRequest(
        expected_version=workspace.task_version,
        expected_control_revision=workspace.control_revision,
        expected_input_validity_revision=workspace.input_validity_revision,
        input_set_ref=input_ref,
        expected_workspace_revision=binding.workspace_revision,
        expected_write_generation=binding.write_generation,
        expected_manifest_digest=manifest_digest,
    )
    accepted = probe.post(
        f"/api/workspaces/{workspace_id}/candidates", request,
        WorkspaceCommandResult, expected=202,
    )
    receipt = operation(probe, workspace_id, accepted)
    snapshot = receipt.snapshot
    candidate = candidate_view(probe, workspace_id, snapshot.candidate_id)
    require(candidate.snapshot == snapshot and snapshot.manifest_digest == manifest_digest,
            "workspace_development_live_candidate_receipt_mismatch")
    return candidate, receipt


def create_synthetic_note(container_id: str, title: str, body: str) -> dict:
    """POST one bounded disposable note through the real backend HTTP endpoint."""
    import json
    import importlib
    import re

    docker = importlib.import_module("services.dev-runner.artifact_environment_docker").docker

    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise WorkspaceDevelopmentCheckFailure("workspace_development_backend_identity_invalid")
    program = """import json,sys,urllib.request
payload=json.load(sys.stdin)
body=json.dumps(payload,separators=(',',':')).encode('utf-8')
request=urllib.request.Request('http://127.0.0.1:8000/api/notes',data=body,
 headers={'Content-Type':'application/json'},method='POST')
with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=4) as response:
 raw=response.read(16385)
 if response.status!=201 or len(raw)>16384: raise SystemExit(81)
value=json.loads(raw.decode('utf-8'))
if value.get('title')!=payload.get('title') or value.get('body')!=payload.get('body') or type(value.get('id')) is not int:
 raise SystemExit(82)
print(json.dumps({'status':201,'id':value['id']},separators=(',',':')))
"""
    payload = json.dumps({"title": title, "body": body}, separators=(",", ":")).encode("utf-8")
    result = docker(
        "exec", "-i", container_id, "/environment/bin/python", "-B", "-I", "-c", program,
        input_bytes=payload, timeout=8,
    )
    if len(result.stdout) > 4096:
        raise WorkspaceDevelopmentCheckFailure("workspace_development_http_note_response_exceeded")
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise WorkspaceDevelopmentCheckFailure("workspace_development_http_note_response_invalid") from None
    require(value == {"status": 201, "id": value.get("id")} and type(value.get("id")) is int,
            "workspace_development_http_note_not_created")
    return value
