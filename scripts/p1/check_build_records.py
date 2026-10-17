"""Narrow real-PostgreSQL build protocol checks with explicitly synthetic inputs."""

import argparse
from datetime import UTC, datetime
import json

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import func, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from database.commands import commands, get_by_id
from database.maintenance import initialize_database
from database.models import load_business_metadata
from database.readiness import DatabaseNotReady
from database.tables import BUSINESS_REVISION, runtime_baseline
from database.uow import UnitOfWork
from modules.artifacts.content_store import ArtifactStore
from modules.collaboration.tables import tasks, work_items
from modules.delivery.commands import BuildApplication, resolve_build_operation_in_uow
from modules.delivery.errors import BuildBoundaryError
from modules.delivery.queries import pending_build_operations, read_build_intent
from modules.delivery.receipts import (
    register_verified_build_content, register_verified_build_observation, verify_build_content, verify_build_observation,
)
from modules.delivery.tables import build_runs
from modules.identity.errors import IdentityError
from modules.identity.tables import role_bindings
from modules.projects.source_tables import project_git_sources
from modules.sync.tables import event_log, outbox
from modules.workspaces.tables import workspace_candidates, workspaces
from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, input_set_digest
from packages.contracts.p1.build_records import BuildArtifactLocator, BuildExecutionArtifact, BuildExecutionObservation
from packages.contracts.p1.build_requests import BuildDefinition, RequestBuildRequest
from packages.contracts.p1.task_facts import InputSetMetadata
from packages.contracts.p1.task_internal import BindInitialTaskInputRequest
from packages.contracts.p1.workspace_git import CandidateSnapshot, RegisteredGitSource, WorkspaceBinding, WorkspaceFiles
from packages.contracts.p1.workspace_records import workspace_metadata_digest
from scripts.p1.check_artifact_content import archive, image
from scripts.p1.database_fixture import database_fixture
from scripts.p1.task_fixture import FixtureSources
from scripts.p1.task_probe import OWNER, PROJECT, TaskProbe

METHOD = "p1-build-records-r1"
DIGEST = "sha256:" + "a" * 64


def require(value, code):
    if not value:
        raise AssertionError(code)


def reject(call, category, code=None):
    try:
        call()
    except category as failure:
        require(code is None or str(failure) == code, "build_wrong_rejection")
    else:
        raise AssertionError("build_expected_rejection_missing")


def _ref(kind, name):
    return EngineeringRef(kind=kind, object_id="build-fixture-" + name, revision="fixture-r1",
                          authority="build-fixture", digest=DIGEST, digest_algorithm="sha256")


def definition(assets):
    file = {"path": "fixture.json", "digest": DIGEST}
    return BuildDefinition(recipes=(file,), locks=(file,), toolchain_refs=(_ref("artifact", "toolchain"),),
                           base_image_refs=(_ref("artifact", "base"),), descriptor=file, compose=file,
                           runtime_contract_ref=_ref("runtime", "runtime"), config_schema=file,
                           migrations=(file,), acceptance_assets_ref=assets)


def seed(probe):
    created = probe.create("build-fixture")
    with UnitOfWork(probe.pools.normal) as uow:
        sources = FixtureSources(uow, PROJECT, probe.token)
        declaration = probe.declaration
        refs = (declaration.requirement_ref, declaration.acceptance_assets_ref, declaration.source_ref,
                declaration.resource_scope_ref, declaration.human_test_policy_ref, sources.method_ref)
        input_set = InputSet(input_set_id="build-fixture-task-inputs", references=refs, set_digest=input_set_digest(refs))
        input_ref = sources.add("build-inputs", InputSetMetadata(input_set=input_set), domain="collaboration")
    bound = probe.app.bind_initial_input(probe.actor(), created.task_id, BindInitialTaskInputRequest(
        expected_version=created.version, expected_control_revision=0, expected_input_validity_revision=0,
        input_set_ref=input_ref,
    ), idempotency_key="build-fixture-bind").body
    with UnitOfWork(probe.maintenance_engine) as uow:
        # Maintenance fixtures establish structure only; no workflow/build succeeded.
        uow.connection.execute(update(tasks).where(tasks.c.task_id == created.task_id).values(state="active"))
        item_id = uow.connection.scalar(select(work_items.c.work_item_id).where(work_items.c.task_id == created.task_id))
        if item_id is None:
            item_id = "build-fixture-work-item"
            declaration_id = uow.connection.scalar(select(tasks.c.declaration_id).where(tasks.c.task_id == created.task_id))
            uow.connection.execute(insert(work_items).values(work_item_id=item_id, task_id=created.task_id,
                declaration_id=declaration_id, goal="Synthetic build-record protocol fixture"))
        authorization = get_by_id(uow.connection, created.command_id).authorization_decision_id
        source = RegisteredGitSource(project_id=PROJECT, source_id="build-fixture-source", source_revision=1,
            kind="managed_bare", target_branch="refs/heads/main", object_format="sha1", access_mode="read_write")
        binding = WorkspaceBinding(workspace_id="build-fixture-workspace", project_id=PROJECT, task_id=created.task_id,
            work_item_id=item_id, owner_user_id=OWNER, source_id=source.source_id, source_revision=1,
            base_commit="1" * 40, workspace_revision=0, write_generation=0)
        files = WorkspaceFiles(binding=binding, operation_id="build-fixture-materialize", storage_id="workspace-" + "1" * 64,
            manifest_digest=DIGEST, file_count=1, total_bytes=1)
        snapshot = CandidateSnapshot(binding=binding, candidate_id="build-fixture-candidate", candidate_commit="2" * 40,
            parent_commit=binding.base_commit, freeze_operation_id="build-fixture-freeze",
            storage_id="candidate-" + "2" * 64, manifest_digest=DIGEST)
        common = dict(authorization_decision_id=authorization, created_by_command_id=created.command_id)
        uow.connection.execute(insert(project_git_sources).values(project_id=PROJECT, source_id=source.source_id,
            source_revision=1, source_json=source.model_dump(mode="json"), source_digest=workspace_metadata_digest(source),
            registered_by_command_id=created.command_id, authorization_decision_id=authorization))
        uow.connection.execute(insert(workspaces).values(**binding.model_dump(), binding_json=binding.model_dump(mode="json"),
            binding_digest=workspace_metadata_digest(binding), files_json=files.model_dump(mode="json"),
            files_digest=workspace_metadata_digest(files), materialization_operation_id=files.operation_id,
            storage_id=files.storage_id, **common))
        uow.connection.execute(insert(workspace_candidates).values(**binding.model_dump(exclude={"base_commit"}),
            **snapshot.model_dump(exclude={"binding", "manifest_digest"}), snapshot_json=snapshot.model_dump(mode="json"),
            snapshot_digest=workspace_metadata_digest(snapshot), **common))
    request = RequestBuildRequest(expected_version=bound.version, expected_control_revision=0,
        expected_input_validity_revision=1, candidate_id=snapshot.candidate_id, input_set_ref=input_ref,
        definition=definition(probe.declaration.acceptance_assets_ref))
    return created.task_id, request


def snapshot(probe, task_id):
    with UnitOfWork(probe.pools.control) as uow:
        version = uow.connection.scalar(select(tasks.c.version).where(tasks.c.task_id == task_id))
        counts = tuple(uow.connection.scalar(select(func.count()).select_from(table))
                       for table in (build_runs, commands, event_log, outbox))
        return version, counts


def grant(probe, actions):
    with UnitOfWork(probe.maintenance_engine) as uow:
        existing = uow.connection.scalar(select(role_bindings.c.binding_id).where(
            role_bindings.c.project_id == PROJECT, role_bindings.c.user_id == OWNER))
        if existing is None:
            uow.connection.execute(insert(role_bindings).values(binding_id="build-fixture-grant", project_id=PROJECT,
                user_id=OWNER, role="developer", actions=actions))
        else:
            uow.connection.execute(update(role_bindings).where(role_bindings.c.binding_id == existing).values(actions=actions))


def structure(probe):
    metadata = load_business_metadata()
    with UnitOfWork(probe.maintenance_engine) as uow:
        context = MigrationContext.configure(uow.connection, opts={"include_schemas": True,
            "include_name": lambda name, kind, parent: kind != "schema" or name == "cloudhelm",
            "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table" or name in {
                "build_runs", "workspaces", "workspace_candidates", "workflow_bindings"}})
        require(not compare_metadata(context, metadata), "build_metadata_migration_drift")
        expected = {constraint.name for constraint in build_runs.constraints if constraint.__class__.__name__ == "CheckConstraint"}
        actual = {constraint["name"] for constraint in inspect(uow.connection).get_check_constraints("build_runs", schema="cloudhelm")}
        require(expected == actual, "build_check_constraints_drift")
        for role in ("api", "worker"):
            require(uow.connection.scalar(text("SELECT has_table_privilege(:role, 'cloudhelm.build_runs', 'INSERT')"),
                                           {"role": "cloudhelm_" + role}), "build_insert_grant_missing")
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                require(not uow.connection.scalar(text("SELECT has_table_privilege(:role, 'cloudhelm.build_runs', :privilege)"),
                    {"role": "cloudhelm_" + role, "privilege": privilege}), "build_mutation_overgrant")


def acceptance(probe, task_id, request):
    app, actor = BuildApplication(probe.pools.normal, probe.pools.control), probe.actor()
    reject(lambda: app.request(actor, task_id, request, idempotency_key="build-main"), IdentityError, "permission_denied")
    grant(probe, ["operation.request"])
    before = snapshot(probe, task_id)
    first = app.request(actor, task_id, request, idempotency_key="build-main")
    after = snapshot(probe, task_id)
    require(first.status_code == 202 and after == (before[0] + 1, tuple(item + 1 for item in before[1])), "build_accept_not_atomic")
    require(app.request(actor, task_id, request, idempotency_key="build-main") == first
            and snapshot(probe, task_id) == after, "build_replay_not_stable")
    changed = request.model_copy(update={"expected_version": first.body.version})
    reject(lambda: app.request(actor, task_id, changed, idempotency_key="build-main"),
           BuildBoundaryError, "idempotency_digest_conflict")
    stale = app.request(actor, task_id, request, idempotency_key="build-stale")
    require(stale.status_code == 409 and stale.body.code == "resource_revision_conflict", "build_stale_allowed")
    grant(probe, ["resource.read"])
    reject(lambda: app.request(actor, task_id, request, idempotency_key="build-main"), IdentityError, "permission_denied")
    grant(probe, ["operation.request"])
    before = snapshot(probe, task_id)
    def fail_enqueue(*args, **kwargs):
        raise AssertionError("build_deliberate_enqueue_failure")
    reject(lambda: BuildApplication(probe.pools.normal, probe.pools.control, enqueue_operation=fail_enqueue).request(
        actor, task_id, changed, idempotency_key="build-rollback"), AssertionError, "build_deliberate_enqueue_failure")
    require(snapshot(probe, task_id) == before, "build_enqueue_partial_commit")
    with UnitOfWork(probe.pools.control) as uow:
        record = resolve_build_operation_in_uow(uow, first.body.operation_id)
        require(record.fixed_inputs.candidate.candidate_id == request.candidate_id
                and len(pending_build_operations(uow.connection, task_id)) == 1, "build_fixed_input_or_pending_missing")
    return app, actor, first, record


def database_boundaries(probe, record):
    with UnitOfWork(probe.maintenance_engine) as uow:
        for changes in ({"fixed_inputs_json": {}}, {"expected_task_version": 0}, {"request_json": {}}):
            try:
                with uow.connection.begin_nested():
                    uow.connection.execute(update(build_runs).where(
                        build_runs.c.operation_id == record.operation_id).values(**changes))
            except DBAPIError as failure:
                require(getattr(failure.orig, "sqlstate", None) == "23514", "build_database_wrong_rejection")
            else:
                raise AssertionError("build_invalid_database_record_allowed")
        row = uow.connection.execute(select(workspaces).where(
            workspaces.c.workspace_id == record.fixed_inputs.candidate.binding.workspace_id)).mappings().one()
        binding = WorkspaceBinding.model_validate({**row["binding_json"], "workspace_revision": 1, "write_generation": 1})
        uow.connection.execute(update(workspaces).where(workspaces.c.workspace_id == row["workspace_id"]).values(
            binding_json=binding.model_dump(mode="json"), binding_digest=workspace_metadata_digest(binding),
            workspace_revision=1, write_generation=1))
        require(uow.connection.scalar(select(workspaces.c.files_json).where(
            workspaces.c.workspace_id == row["workspace_id"])) == row["files_json"], "workspace_original_receipt_changed")
        invalid = {**row["files_json"], "binding": {**row["files_json"]["binding"], "write_generation": 2}}
        try:
            with uow.connection.begin_nested():
                uow.connection.execute(update(workspaces).where(workspaces.c.workspace_id == row["workspace_id"]).values(files_json=invalid))
        except DBAPIError as failure:
            require(getattr(failure.orig, "sqlstate", None) == "23514", "workspace_original_counter_wrong_rejection")
        else:
            raise AssertionError("workspace_future_original_receipt_allowed")


class SyntheticObservationProducer:
    """Protocol-only fixture; never evidence of a real Runner or successful build."""
    def __init__(self, observation):
        self.observation = observation

    def read_verified_build_observation(self, operation_id):
        return self.observation


def content_and_observations(probe, app, actor, task_id, record):
    base = probe.fixture.runtime_dir
    incoming, root = base / "build-incoming", base / "build-content"
    incoming.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    source = incoming / "synthetic.oci.tar"
    source.write_bytes(archive(image()))
    with ArtifactStore(root) as store:
        content = store.publish(source)
        locators = tuple(BuildArtifactLocator(role=role, storage_id=content.storage_id)
                         for role in ("frontend", "backend", "postgres"))
        reject(lambda: verify_build_content(record, store, locators[:1]), BuildBoundaryError, "build_artifact_roles_incomplete")
        proof = verify_build_content(record, store, locators)
        with UnitOfWork(probe.pools.normal) as uow:
            reject(lambda: register_verified_build_content(uow, record.operation_id, content),
                   BuildBoundaryError, "verified_build_content_required")
            registered = register_verified_build_content(uow, record.operation_id, proof)
            require(register_verified_build_content(uow, record.operation_id, proof) == registered, "build_content_replay_changed")
        view = app.query(actor, task_id, record.operation_id)
        require(view.state == "accepted" and view.content_verified, "content_claimed_build_success")
        with UnitOfWork(probe.pools.control) as uow:
            require(len(pending_build_operations(uow.connection, task_id)) == 1, "content_closed_pending_build")
        running = BuildExecutionObservation(observation_id="build-fixture-running", operation_id=record.operation_id,
            request_digest=record.request_digest, build_input_digest=record.build_input_digest, executor_instance_id="fixture-runner",
            executor_generation=1, closure="running", method_ref=_ref("method", "synthetic-protocol"), observed_at=datetime.now(UTC))
        reject(lambda: verify_build_observation(record.operation_id, running), BuildBoundaryError, "trusted_build_observation_required")
        with UnitOfWork(probe.pools.normal) as uow:
            register_verified_build_observation(uow, record.operation_id,
                verify_build_observation(record.operation_id, SyntheticObservationProducer(running)))
        require(app.query(actor, task_id, record.operation_id).state == "running", "build_running_missing")
        ended = BuildExecutionObservation.model_validate({**running.model_dump(mode="python"),
            "observation_id": "build-fixture-ended", "previous_observation_id": running.observation_id,
            "closure": "ended_reconciled", "exit_code": 0, "artifacts": tuple(BuildExecutionArtifact(
                role=item.role, storage_id=item.storage_id, manifest_digest=content.manifest.digest,
                config_digest=content.config.digest, loaded_image_id=content.image_id) for item in locators),
            "observed_at": datetime.now(UTC)})
        with UnitOfWork(probe.pools.normal) as uow:
            register_verified_build_observation(uow, record.operation_id,
                verify_build_observation(record.operation_id, SyntheticObservationProducer(ended)))
            require(not pending_build_operations(uow.connection, task_id), "trusted_protocol_closure_not_projected")
        require(app.query(actor, task_id, record.operation_id).state == "succeeded", "build_matching_content_result_missing")
        current = probe.row(task_id)
        later_request = RequestBuildRequest(expected_version=current["version"],
            expected_control_revision=current["control_revision"],
            expected_input_validity_revision=current["input_validity_revision"],
            input_set_ref=record.fixed_inputs.source_input_set_ref,
            candidate_id=record.fixed_inputs.candidate.candidate_id, definition=record.fixed_inputs.definition)
        later = app.request(actor, task_id, later_request, idempotency_key="build-late")
        require(later.status_code == 202, "build_late_intent_missing")
        with UnitOfWork(probe.pools.control) as uow:
            _, later_record = read_build_intent(uow.connection, later.body.operation_id)
        later_proof = verify_build_content(later_record, store, locators)
        # A closed Task keeps late facts but cannot regain ordinary progress.
        with UnitOfWork(probe.maintenance_engine) as uow:
            uow.connection.execute(update(tasks).where(tasks.c.task_id == task_id).values(ordinary_progress_closed=True))
        before = probe.row(task_id)
        with UnitOfWork(probe.pools.normal) as uow:
            late_content = register_verified_build_content(uow, later.body.operation_id, later_proof)
            require(not late_content.applicable, "late_build_content_marked_applicable")
        denied = app.request(actor, task_id, RequestBuildRequest(expected_version=before["version"],
            expected_control_revision=0, expected_input_validity_revision=1, candidate_id=record.fixed_inputs.candidate.candidate_id,
            input_set_ref=record.fixed_inputs.source_input_set_ref, definition=record.fixed_inputs.definition),
            idempotency_key="build-closed")
        require(denied.status_code == 409 and denied.body.code == "task_progress_closed", "closed_task_build_allowed")
        require(probe.row(task_id) == before, "late_build_fact_revived_task")


def old_baseline(probe):
    with UnitOfWork(probe.maintenance_engine) as uow:
        uow.connection.execute(update(runtime_baseline).values(business_revision="0002_p1_2"))
    reject(lambda: initialize_database(probe.fixture.settings("migrator")), DatabaseNotReady, "database_baseline_incompatible")
    with UnitOfWork(probe.maintenance_engine) as uow:
        require(uow.connection.scalar(select(runtime_baseline.c.business_revision)) == "0002_p1_2"
                and uow.connection.scalar(text("SELECT version_num FROM cloudhelm.alembic_version")) == BUSINESS_REVISION,
                "build_old_baseline_mutated")
        uow.connection.execute(update(runtime_baseline).values(business_revision=BUSINESS_REVISION))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=55438)
    options = parser.parse_args()
    started = datetime.now(UTC).isoformat()
    print(json.dumps({"status": "running", "method": METHOD, "started_at": started}), flush=True)
    scene = "database_fixture"
    try:
        with database_fixture(port=options.port) as fixture:
            probe = TaskProbe(fixture)
            try:
                scene = "identity_fixture"
                probe.open()
                scene = "build_input_fixture"
                task_id, request = seed(probe)
                scene = "build_structure"
                structure(probe)
                scene = "build_acceptance"
                app, actor, first, record = acceptance(probe, task_id, request)
                scene = "build_database_boundaries"
                database_boundaries(probe, record)
                scene = "build_content_and_observations"
                content_and_observations(probe, app, actor, task_id, record)
                scene = "old_baseline"
                old_baseline(probe)
            finally:
                # Only this method's disposable read-only OCI folders are made
                # removable; retained production stores are never traversed.
                content_root = fixture.runtime_dir / "build-content"
                if content_root.is_dir():
                    for path in content_root.iterdir():
                        if path.is_dir() and not path.is_symlink() and path.name.startswith("oci-"):
                            path.chmod(0o700)
                probe.close()
        print(json.dumps({"status": "passed", "method": METHOD, "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(), "baseline": BUSINESS_REVISION,
            "input_kind": "development_worktree", "cleanup": "complete", "complete_scope": False,
            "scope": "synthetic build protocol, real PostgreSQL and synthetic OCI content; no Runner build or product acceptance"}))
        return 0
    except Exception as failure:
        code = str(failure) if isinstance(failure, (AssertionError, BuildBoundaryError)) else type(failure).__name__
        errors = [{"field": ".".join(str(part) for part in error["loc"]), "type": error["type"]}
                  for error in failure.errors(include_input=False, include_context=False)] if isinstance(failure, ValidationError) else []
        print(json.dumps({"status": "failed", "method": METHOD, "scene": scene, "reason": code,
                          "fields": errors, "finished_at": datetime.now(UTC).isoformat()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
