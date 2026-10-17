"""Narrow workspace commands/receipt checks; no production admission or candidate freeze claim."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select

from database.commands import CommandConflict, commands
from database.uow import UnitOfWork
from modules.collaboration.facts import load_cancellation_facts, load_task_control_facts
from modules.collaboration.reference_inputs import ReferenceTaskApplication
from modules.identity.errors import IdentityError
from modules.identity.tables import project_policies
from modules.projects.commands import ProjectApplication
from modules.projects.tables import projects
from modules.sync.tables import event_log
from modules.workspaces.application import WorkspaceApplication
from modules.workspaces.commands import accept_workspace_command_in_uow
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.git_objects import GitObjectStore
from modules.workspaces.operations import (
    WorkspaceError, WorkspaceOperationIntent, mutation_spec, operation_request_digest, resolve_workspace_operation_in_uow,
)
from modules.workspaces.receipts import register_workspace_receipt_in_uow, verify_materialization
from modules.workspaces.source_import import ReferenceSourceImporter
from modules.workspaces.tables import workspaces
from modules.workspaces.workfiles import WorkfileStore
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.identity_requests import GrantProjectRoleRequest, RevokeProjectRoleRequest
from packages.contracts.p1.source_requests import ImportReferenceSourceRequest
from packages.contracts.p1.workspace_git import (
    WorkspaceBinding, WorkspaceFile, WorkspaceFiles, content_digest, workspace_mutation_digest,
)
from packages.contracts.p1.workspace_records import WorkspaceRecord, workspace_metadata_digest
from packages.contracts.p1.workspace_requests import (
    CreateWorkspaceRequest, MaterializeWorkspaceRequest, MutateWorkspaceFileRequest,
    SubmitWorkspaceCandidateRequest, WorkspaceCommandResult,
)
from scripts.p1.check_source_commands import OWNER, PROJECT, SourceCommandCheckFailure, SourceProbe, reject, require
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture

ROOT = Path(__file__).resolve().parents[2]
CONTENT = b"workspace application receipt check\n"


def contracts():
    reference = EngineeringRef(kind="input_set", object_id="inputs", revision="r1", authority="collaboration",
                               digest="sha256:" + "1" * 64, digest_algorithm="sha256")
    guard = dict(expected_version=2, expected_control_revision=0, expected_input_validity_revision=1,
                 input_set_ref=reference)
    for extra in ({"path": "/tmp/forbidden"}, {"reserved": True}, {"source_id": "arbitrary"},
                  {"allowed": True}, {"expected_version": True}):
        reject(lambda extra=extra: CreateWorkspaceRequest.model_validate({**guard, **extra}), ValidationError)
    versioned = {**guard, "expected_workspace_revision": 1, "expected_write_generation": 1}
    replacement = WorkspaceFile(path="proof.txt", mode="100644", size_bytes=len(CONTENT), content_digest=content_digest(CONTENT))
    request = MutateWorkspaceFileRequest(**versioned, action="write", path=replacement.path,
                                         expected_manifest_digest="sha256:" + "2" * 64,
                                         expected_file=None, replacement=replacement)
    for extra in ({"path": "../escape"}, {"content": "never durable"}, {"replacement": None}):
        reject(lambda extra=extra: MutateWorkspaceFileRequest.model_validate({**request.model_dump(), **extra}), ValidationError)
    reject(lambda: SubmitWorkspaceCandidateRequest(**versioned, expected_manifest_digest="sha256:" + "2" * 64,
                                                   runtime_scope_id="client-assertion"), ValidationError)
    binding = WorkspaceBinding(workspace_id="workspace", project_id="project", task_id="task", work_item_id="item",
                               owner_user_id="owner", source_id="source", source_revision=1, base_commit="a" * 40,
                               workspace_revision=1, write_generation=1)
    result = WorkspaceCommandResult(command_id="a" * 32, task_id="task", kind="mutate", outcome="accepted", code="accepted",
                                     version=3, control_revision=0, input_validity_revision=1, input_set_ref=reference,
                                     workspace_id="workspace", binding=binding, operation_id="workspace-mutate-" + "a" * 32,
                                     request_digest="sha256:" + "0" * 64)
    intent = WorkspaceOperationIntent(request=request, result=result, materialization_operation_id="materialize")
    spec = mutation_spec(intent, CONTENT)
    require(operation_request_digest(intent) == workspace_mutation_digest(spec), "workspace_metadata_bytes_digest_mismatch")
    reject(lambda: mutation_spec(intent, b"different bytes"), WorkspaceError, "workspace_mutation_content_mismatch")
    original = WorkspaceFiles(binding=binding, operation_id="materialize", storage_id="workspace-" + "3" * 64,
                              manifest_digest="sha256:" + "2" * 64, file_count=1, total_bytes=20)
    current = binding.model_copy(update={"workspace_revision": 2, "write_generation": 2})
    values = dict(binding=current, binding_digest=workspace_metadata_digest(current), files=original,
                  files_digest=workspace_metadata_digest(original), created_by_command_id="created",
                  authorization_decision_id="decision", created_at=datetime.now(UTC))
    record = WorkspaceRecord(**values)
    require(record.files == original, "workspace_initial_receipt_was_rebound")
    changed = current.model_copy(update={"source_id": "another"})
    reject(lambda: WorkspaceRecord(**{**values, "binding": changed, "binding_digest": workspace_metadata_digest(changed)}),
           ValidationError)
    return {"public_assertions_paths_and_bytes_rejected": True, "mutation_bytes_rechecked_by_digest": True,
            "immutable_initial_receipt_with_new_current_binding": True}


def snapshot(probe):
    with UnitOfWork(probe.pools.control) as uow:
        return tuple(uow.connection.scalar(select(func.count()).select_from(table)) for table in (commands, event_log, workspaces))


def revisions(probe):
    with UnitOfWork(probe.pools.control) as uow:
        row = uow.connection.execute(select(projects.c.revision, project_policies.c.authorization_revision).join(
            project_policies, project_policies.c.project_id == projects.c.project_id,
        ).where(projects.c.project_id == PROJECT)).one()
        return dict(expected_project_revision=row.revision, expected_permission_revision=row.authorization_revision)


def request_guard(view, input_set_ref):
    binding = view.workspace.binding
    return dict(expected_version=view.task_version, expected_control_revision=view.control_revision,
                expected_input_validity_revision=view.input_validity_revision, input_set_ref=input_set_ref,
                expected_workspace_revision=binding.workspace_revision, expected_write_generation=binding.write_generation)


def assert_pending(probe, task_id, operation_id, expected):
    with UnitOfWork(probe.worker_engine) as uow:
        for facts in (load_task_control_facts(uow.connection, task_id).facts, load_cancellation_facts(uow.connection, task_id)):
            actual = any(item.operation_ref.object_id == operation_id and item.closure == "unknown" for item in facts.operations)
            require(actual == expected, "workspace_task_pending_projection_wrong")


def run_database(fixture):
    probe, resources = None, []
    scene = "workspace_fixture_failed"
    try:
        probe = SourceProbe(fixture)
        scene = "workspace_real_inputs_failed"
        source = probe.app.import_reference(probe.actor, PROJECT, ImportReferenceSourceRequest(expected_project_revision=1),
                                           idempotency_key="workspace-source")
        repositories, storage = fixture.runtime_dir / "workspace-git", fixture.runtime_dir / "workspace-files"
        repositories.mkdir(mode=0o700)
        storage.mkdir(mode=0o700)
        importer = ReferenceSourceImporter(repositories, ROOT, probe.worker.resolve_import_operation)
        resources.append(importer)
        importer.import_reference(source.body.operation_id)
        registered = probe.worker.finish_import(source.body.operation_id, importer)
        bound = ReferenceTaskApplication(probe.pools.normal, ROOT).create(
            probe.actor, PROJECT, registered, expected_project_revision=source.body.project_revision,
            idempotency_key="workspace-inputs",
        )
        application = WorkspaceApplication(probe.pools.normal, probe.pools.control, runtime_scope_for=lambda binding: "fixture-runtime")
        worker = WorkspaceApplication(probe.worker_engine, probe.worker_engine)
        guard = dict(expected_version=bound.bound.body.version, expected_control_revision=0,
                     expected_input_validity_revision=1, input_set_ref=bound.inputs.input_set_ref)
        create_request = CreateWorkspaceRequest(**guard)
        scene = "workspace_authority_and_creation_failed"
        reject(lambda: application.create(probe.actor, bound.task_id, create_request, idempotency_key="workspace-create"),
               IdentityError, "permission_denied")
        project_app = ProjectApplication(probe.pools.normal)
        grant = project_app.grant_role(probe.actor, PROJECT, GrantProjectRoleRequest(
            **revisions(probe), user_id=OWNER, role="developer", actions=("workspace.write", "candidate.submit"),
        ), idempotency_key="workspace-grant")
        created = application.create(probe.actor, bound.task_id, create_request, idempotency_key="workspace-create")
        require(created.status_code == 201, "workspace_create_rejected")
        workspace_id = created.body.workspace_id
        require(application.create(probe.actor, bound.task_id, create_request, idempotency_key="workspace-create") == created,
                "workspace_create_replay_changed")
        reject(lambda: application.create(probe.actor, bound.task_id, CreateWorkspaceRequest(**guard, goal="changed"),
                                          idempotency_key="workspace-create"), CommandConflict, "idempotency_digest_conflict")
        view = application.query(probe.actor, workspace_id)
        before = snapshot(probe)
        scene = "workspace_transaction_rollback_failed"
        try:
            with UnitOfWork(probe.pools.normal) as uow:
                accept_workspace_command_in_uow(uow, probe.actor, bound.task_id, CreateWorkspaceRequest(
                    **{**guard, "expected_version": view.task_version},
                ), idempotency_key="workspace-rollback")
                raise SourceCommandCheckFailure("workspace_deliberate_rollback")
        except SourceCommandCheckFailure:
            pass
        require(snapshot(probe) == before, "workspace_rollback_leaked_records")
        materialize_request = MaterializeWorkspaceRequest(**request_guard(view, bound.inputs.input_set_ref))
        for field, value, code in (
            ("expected_version", 0, "resource_revision_conflict"),
            ("expected_control_revision", 1, "control_revision_conflict"),
            ("expected_input_validity_revision", 2, "input_validity_revision_conflict"),
            ("expected_workspace_revision", 0, "workspace_revision_conflict"),
            ("expected_write_generation", 0, "workspace_write_generation_conflict"),
        ):
            refused = application.materialize(probe.actor, workspace_id, MaterializeWorkspaceRequest.model_validate({
                **materialize_request.model_dump(), field: value,
            }), idempotency_key="stale-" + field)
            require(refused.status_code == 409 and refused.body.code == code, "workspace_stale_guard_allowed")
        before = snapshot(probe)
        def failed_enqueue(*args):
            raise WorkspaceError("workspace_fixture_enqueue_failure")
        with UnitOfWork(probe.pools.normal) as uow:
            reject(lambda: accept_workspace_command_in_uow(
                uow, probe.actor, bound.task_id, materialize_request, idempotency_key="materialize",
                workspace_id=workspace_id, enqueue_operation=failed_enqueue,
            ), WorkspaceError, "workspace_fixture_enqueue_failure")
        require(snapshot(probe) == before, "workspace_enqueue_failure_did_not_roll_back")
        materialized = application.materialize(probe.actor, workspace_id, materialize_request, idempotency_key="materialize")
        require(materialized.status_code == 202, "workspace_materialize_not_accepted")
        operation = materialized.body.operation_id
        assert_pending(probe, bound.task_id, operation, True)
        reject(lambda: worker.resolve_materialization_operation(operation), WorkspaceError, "workspace_execution_admission_unavailable")
        reject(lambda: worker.finish_materialization(operation, materialized.body.binding), WorkspaceError, "trusted_workfile_store_required")
        git = GitObjectStore(repositories)
        resources.append(git)
        git.register_source(registered.source_record.source)
        # Disposable protocol storage deliberately bypasses physical admission.
        # Production resolver defaults remain closed and are checked above.
        def protocol_intent(operation_id):
            with UnitOfWork(probe.worker_engine) as uow:
                return resolve_workspace_operation_in_uow(uow, operation_id)[0]
        writer = WorkfileStore(storage, git, lambda op: protocol_intent(op).result.binding)
        reader = WorkfileStore(storage, git, lambda op: worker.resolve_materialization_operation(op, reconciliation=True))
        resources.extend((writer, reader))
        scene = "workspace_materialization_receipt_failed"
        actual = writer.materialize(materialized.body.binding, operation)
        require(application.query_operation(probe.actor, workspace_id, operation).state == "accepted",
                "workspace_self_reported_materialization_success")
        verified = verify_materialization(operation, materialized.body.binding, reader)
        before = snapshot(probe)
        try:
            with UnitOfWork(probe.worker_engine) as uow:
                register_workspace_receipt_in_uow(uow, operation, verified)
                raise SourceCommandCheckFailure("workspace_deliberate_receipt_rollback")
        except SourceCommandCheckFailure:
            pass
        require(snapshot(probe) == before and reader.query(materialized.body.binding, operation) == actual,
                "workspace_receipt_rollback_changed_physical_bytes")
        registration = worker.finish_materialization(operation, reader)
        require(registration.receipt == actual and registration.applicable, "workspace_materialization_not_registered")
        require(worker.finish_materialization(operation, reader) == registration, "workspace_materialization_receipt_replay_changed")
        assert_pending(probe, bound.task_id, operation, False)
        view = application.query(probe.actor, workspace_id)
        replacement = WorkspaceFile(path="workspace-proof.txt", mode="100644", size_bytes=len(CONTENT), content_digest=content_digest(CONTENT))
        mutation_request = MutateWorkspaceFileRequest(**request_guard(view, bound.inputs.input_set_ref), action="write",
                                                      path=replacement.path, expected_manifest_digest=actual.manifest_digest,
                                                      expected_file=None, replacement=replacement)
        mutation = application.mutate(probe.actor, workspace_id, mutation_request, idempotency_key="mutation")
        operation = mutation.body.operation_id
        scene = "workspace_mutation_receipt_failed"
        file_writer = WorkspaceFileService(storage, git, lambda op: mutation_spec(protocol_intent(op), CONTENT))
        file_reader = WorkspaceFileService(storage, git, lambda op: worker.resolve_mutation_operation(op, CONTENT, reconciliation=True))
        resources.extend((file_writer, file_reader))
        actual_mutation = file_writer.apply(operation)
        assert_pending(probe, bound.task_id, operation, True)
        registered_mutation = worker.finish_mutation(operation, file_reader)
        view = application.query(probe.actor, workspace_id)
        require(registered_mutation.receipt == actual_mutation and view.workspace.binding.workspace_revision == 2
                and view.workspace.binding.write_generation == 2 and view.workspace.files == actual,
                "workspace_mutation_or_original_receipt_changed")
        require(application.mutate(probe.actor, workspace_id, mutation_request, idempotency_key="mutation") == mutation,
                "workspace_mutation_original_result_not_replayed")
        assert_pending(probe, bound.task_id, operation, False)
        candidate = application.submit_candidate(probe.actor, workspace_id, SubmitWorkspaceCandidateRequest(
            **request_guard(view, bound.inputs.input_set_ref), expected_manifest_digest=actual_mutation.after_manifest_digest,
        ), idempotency_key="candidate")
        require(candidate.status_code == 202, "workspace_candidate_intent_rejected")
        assert_pending(probe, bound.task_id, candidate.body.operation_id, True)
        scene = "workspace_current_permission_before_replay_failed"
        project_app.revoke_role(probe.actor, PROJECT, RevokeProjectRoleRequest(
            **revisions(probe), binding_id=grant.body.role_binding.binding_id,
        ), idempotency_key="workspace-revoke")
        reject(lambda: application.create(probe.actor, bound.task_id, create_request, idempotency_key="workspace-create"),
               IdentityError, "permission_denied")
        reject(lambda: worker.resolve_candidate_operation(candidate.body.operation_id), IdentityError, "permission_denied")
        return {"real_source_and_task_input_used": True, "explicit_action_and_current_permission_before_replay": True,
                "stable_result_and_conflicting_digest": True, "command_and_enqueue_rollback": True,
                "task_control_input_workspace_generation_conflicts": True, "receipt_rollback_preserves_physical_result": True,
                "real_materialization_and_mutation_receipts": True, "original_files_receipt_preserved": True,
                "pending_blocks_task_completion_and_cancellation": True, "candidate_intent_only_pending": True,
                "production_admission_missing_rejected": True, "physical_resource_admission": "not_exercised",
                "candidate_physical_freeze": "not_executed", "worker_scheduling": "not_executed"}
    except SourceCommandCheckFailure:
        raise
    except Exception as failure:
        error = SourceCommandCheckFailure(scene)
        error.failure_kind = type(failure).__name__
        raise error from None
    finally:
        for resource in reversed(resources):
            resource.close()
        if probe is not None:
            probe.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--contracts-only", action="store_true")
    mode.add_argument("--development", action="store_true")
    parser.add_argument("--port", type=int, default=55439)
    args = parser.parse_args()
    report = dict(method_revision="p1-workspace-application-r1", mode="development_worktree", complete_scope=False,
                  started_at_utc=datetime.now(UTC).isoformat())
    try:
        report["contracts"] = contracts()
        if args.development:
            with database_fixture(port=args.port) as fixture:
                report["fixture_id"] = fixture.project_name
                report["checks"] = run_database(fixture)
            report["cleanup"] = "complete"
        report["status"] = "passed"
    except (SourceCommandCheckFailure, DatabaseFixtureError) as failure:
        report.update(status="failed", failure_code=str(failure))
        if hasattr(failure, "failure_kind"):
            report["failure_kind"] = failure.failure_kind
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
