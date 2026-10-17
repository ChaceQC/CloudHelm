"""One HTTP/DBOS source, real Task, workspace and immutable candidate chain."""

from modules.workspaces.queries import WorkspaceOperationView
from modules.workspaces.reference_seed import REFERENCE_COMMIT
from packages.contracts.p1.identity_requests import GrantProjectRoleRequest, RevokeProjectRoleRequest
from packages.contracts.p1.identity_results import ProjectCommandResult
from packages.contracts.p1.reference_requests import CreateReferenceTaskRequest, ReferenceTaskResult
from packages.contracts.p1.source_requests import ImportReferenceSourceRequest, SourceImportCommandResult, SourceImportView
from packages.contracts.p1.task_requests import StartTaskRequest, TaskBudget
from packages.contracts.p1.task_results import TaskCommandResult, TaskView
from packages.contracts.p1.workspace_git import WorkspaceFile, content_digest
from packages.contracts.p1.workspace_records import PhysicalCandidateRecord
from packages.contracts.p1.workspace_requests import (
    CreateWorkspaceRequest, MaterializeWorkspaceRequest, MutateWorkspaceFileRequest,
    SubmitWorkspaceCandidateRequest, WorkspaceCommandResult, WorkspaceView,
)
from scripts.p1.engineering_fixture import ENGINEERING_ACTIONS, OWNER, PROJECT, require

PROOF_PATH = "cloudhelm-engineering-proof.txt"
FROZEN_CONTENT = "Fixed candidate proof for the real P1.2 engineering chain.\n"
RESUMED_CONTENT = "Development resumed after the candidate was fixed.\n"


def grant_engineering(probe):
    project = probe.project()
    granted = probe.post(f"/api/projects/{PROJECT}/role-bindings", GrantProjectRoleRequest(
        expected_project_revision=project.revision, expected_permission_revision=project.permission_revision,
        user_id=OWNER, role="developer", actions=ENGINEERING_ACTIONS,
    ), ProjectCommandResult, expected=200)
    require(granted.role_binding is not None and set(granted.role_binding.actions) == set(ENGINEERING_ACTIONS),
            "engineering_explicit_grant_missing")
    probe.evidence["explicit_engineering_grant"] = granted.role_binding.model_dump(mode="json")
    return granted.role_binding.binding_id


def accept_source(probe):
    source = probe.post(f"/api/projects/{PROJECT}/source-imports", ImportReferenceSourceRequest(
        expected_project_revision=probe.project().revision,
    ), SourceImportCommandResult, expected=202)
    require(source.outcome == "accepted", "engineering_source_not_accepted")
    workflow = probe.handoff(source)
    current = probe.get(f"/api/projects/{PROJECT}/source-imports/{source.operation_id}", SourceImportView)
    require(current.state == "accepted" and current.registration is None,
            "engineering_source_accepted_misreported_as_completed")
    probe.evidence["source_accepted_before_worker"] = source.model_dump(mode="json")
    return source, workflow


def reference_task(probe, source, workflow):
    registered = probe.wait(f"/api/projects/{PROJECT}/source-imports/{source.operation_id}",
        SourceImportView, lambda value: value.state == "registered", workflow_id=workflow)
    require(registered.registration.source_ref.revision != REFERENCE_COMMIT,
            "engineering_managed_source_did_not_import_fixed_subtree")
    result = probe.post(f"/api/projects/{PROJECT}/reference-tasks", CreateReferenceTaskRequest(
        source_operation_id=source.operation_id, expected_project_revision=probe.project().revision,
        title="Verify the fixed reference engineering chain",
        goal="Materialize, modify, freeze and build the fixed reference in controlled local development.",
        budget=TaskBudget(amount="0", currency="USD"),
    ), ReferenceTaskResult, expected=201)
    created = result.task
    require(created.state == "draft" and created.input_validity_revision == 1,
            "engineering_real_initial_task_input_missing")
    started = probe.post(f"/api/tasks/{created.task_id}/start", StartTaskRequest(
        expected_version=created.version, expected_control_revision=created.control_revision,
        expected_input_validity_revision=created.input_validity_revision,
    ), TaskCommandResult, expected=202)
    active = probe.wait(f"/api/tasks/{created.task_id}", TaskView,
        lambda value: value.state == "active" and bool(value.work_items), workflow_id=started.workflow_id)
    require(active.declaration.source_ref == registered.registration.source_ref and active.input_status == "valid",
            "engineering_task_did_not_consume_real_source")
    probe.evidence["source_registered"] = registered.model_dump(mode="json")
    probe.evidence["task_initial_input"] = result.model_dump(mode="json")
    probe.evidence["task_started"] = started.model_dump(mode="json")
    return active, result.input_set_ref


def task_guard(view, input_ref):
    return dict(expected_version=view.task_version, expected_control_revision=view.control_revision,
                expected_input_validity_revision=view.input_validity_revision, input_set_ref=input_ref)


def workspace_guard(view, input_ref):
    binding = view.workspace.binding
    return {**task_guard(view, input_ref), "expected_workspace_revision": binding.workspace_revision,
            "expected_write_generation": binding.write_generation}


def operation(probe, workspace_id, result):
    require(result.outcome == "accepted", "engineering_workspace_operation_not_accepted")
    workflow = probe.handoff(result)
    value = probe.wait(f"/api/workspaces/{workspace_id}/operations/{result.operation_id}",
        WorkspaceOperationView, lambda value: value.state == "registered", workflow_id=workflow)
    require(value.registration.applicable, "engineering_workspace_receipt_not_applicable")
    probe.evidence.setdefault("workspace_operations", []).append(value.model_dump(mode="json"))
    return value.registration.receipt


def materialize(probe, active, input_ref):
    key = probe.key("create-workspace")
    request = CreateWorkspaceRequest(expected_version=active.version, expected_control_revision=active.control_revision,
        expected_input_validity_revision=active.input_validity_revision, input_set_ref=input_ref)
    created = probe.post(f"/api/tasks/{active.task_id}/workspaces", request,
                         WorkspaceCommandResult, expected=201, key=key)
    view = probe.get(f"/api/workspaces/{created.workspace_id}", WorkspaceView)
    stale = MaterializeWorkspaceRequest(**{**workspace_guard(view, input_ref), "expected_workspace_revision": 0})
    refused = probe.post(f"/api/workspaces/{created.workspace_id}/materialize", stale,
                         WorkspaceCommandResult, expected=409)
    require(refused.code == "workspace_revision_conflict" and refused.operation_id is None,
            "engineering_stale_workspace_revision_allowed")
    accepted = probe.post(f"/api/workspaces/{created.workspace_id}/materialize",
        MaterializeWorkspaceRequest(**workspace_guard(view, input_ref)), WorkspaceCommandResult, expected=202)
    receipt = operation(probe, created.workspace_id, accepted)
    require(receipt.binding == created.binding and receipt.file_count == 32,
            "engineering_reference_files_not_materialized")
    probe.evidence["workspace_created"] = created.model_dump(mode="json")
    probe.evidence["stale_workspace_revision_rejected"] = refused.model_dump(mode="json")
    return created.workspace_id, receipt.manifest_digest, request, key


def mutate(probe, workspace_id, input_ref, before_manifest, content, previous_file=None):
    view = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    raw = content.encode("utf-8")
    replacement = WorkspaceFile(path=PROOF_PATH, mode="100644", size_bytes=len(raw), content_digest=content_digest(raw))
    request = MutateWorkspaceFileRequest(**workspace_guard(view, input_ref), action="write", path=PROOF_PATH,
        expected_manifest_digest=before_manifest, expected_file=previous_file, replacement=replacement)
    accepted = probe.post(f"/api/workspaces/{workspace_id}/files", {
        "request": request.model_dump(mode="json"), "content_utf8": content,
    }, WorkspaceCommandResult, expected=202)
    receipt = operation(probe, workspace_id, accepted)
    require(receipt.after_manifest_digest != before_manifest, "engineering_controlled_write_did_not_change_files")
    return receipt.after_manifest_digest, replacement


def freeze_candidate(probe, workspace_id, input_ref, manifest):
    view = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    accepted = probe.post(f"/api/workspaces/{workspace_id}/candidates", SubmitWorkspaceCandidateRequest(
        **workspace_guard(view, input_ref), expected_manifest_digest=manifest,
    ), WorkspaceCommandResult, expected=202)
    receipt = operation(probe, workspace_id, accepted)
    snapshot = receipt.snapshot
    candidate = probe.get(f"/api/workspaces/{workspace_id}/candidates/{snapshot.candidate_id}", PhysicalCandidateRecord)
    require(candidate.snapshot == snapshot and snapshot.manifest_digest == manifest,
            "engineering_candidate_metadata_mismatch")
    probe.evidence["candidate"] = candidate.model_dump(mode="json")
    probe.evidence["candidate_freeze"] = receipt.model_dump(mode="json")
    return candidate


def revoke_and_check_replay(probe, task_id, binding_id, request, key):
    current = probe.project()
    revoked = probe.post(f"/api/projects/{PROJECT}/role-bindings/revoke", RevokeProjectRoleRequest(
        expected_project_revision=current.revision, expected_permission_revision=current.permission_revision,
        binding_id=binding_id,
    ), ProjectCommandResult, expected=200)
    require(revoked.role_binding is not None and revoked.role_binding.revoked,
            "engineering_grant_not_revoked")
    denied = probe.request("POST", f"/api/tasks/{task_id}/workspaces", body=request, expected=403, key=key)
    require(denied.get("code") == "permission_denied", "engineering_revoked_replay_returned_original_success")
    probe.evidence["revoked_replay_rejected"] = {"binding_id": binding_id, "status_code": 403,
                                                "code": "permission_denied"}
