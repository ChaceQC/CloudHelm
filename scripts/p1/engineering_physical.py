"""Independent candidate-byte and actual Build/three-artifact environment checks."""

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

from modules.artifacts.content_store import ArtifactStore
from modules.projects.reference_assets import load_reference_assets
from modules.workspaces.safe_paths import PrivateRoot, directory_at, read_regular
from modules.workspaces.workspace_views import observe
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_records import BuildView
from packages.contracts.p1.build_requests import BuildCommandResult, RequestBuildRequest
from packages.contracts.p1.development_environment import ArtifactEnvironmentSpec
from packages.contracts.p1.task_results import TaskView
from scripts.p1.engineering_chain import PROOF_PATH
from scripts.p1.engineering_fixture import ROOT, registry_module, require


def candidate_files(storage_ref, candidate):
    """Only regular files under the registered immutable candidate are consumed."""
    storage_api = import_module("services.dev-runner.development_storage")
    snapshot = candidate.snapshot
    with storage_api.DevelopmentStorage(storage_ref.storage_id).admit_ref(storage_ref, requested_bytes=0) as admission:
        root = PrivateRoot(admission.directory)
        try:
            with root.exclusive() as directory:
                with directory_at(directory, "candidates/" + snapshot.storage_id + "/files") as files:
                    observed = observe(files)
                    require(observed.digest == snapshot.manifest_digest,
                            "engineering_candidate_bytes_do_not_match_snapshot")
                    values = {item.path: read_regular(files, item.path, max(1, item.size_bytes))
                              for item in observed.manifest.files}
                    require(not any(".git" in name.split("/") for name in values),
                            "engineering_candidate_exposes_git_metadata")
                    return values, {"manifest_digest": observed.digest, "file_count": len(values),
                        "total_bytes": sum(len(raw) for raw in values.values()),
                        "candidate_commit": snapshot.candidate_commit,
                        "parent_commit": snapshot.parent_commit, "storage_id": snapshot.storage_id}
        finally:
            root.close()


def observe_candidate(storage_ref, candidate, expected_proof):
    values, observation = candidate_files(storage_ref, candidate)
    require(values.get(PROOF_PATH) == expected_proof.encode("utf-8"),
            "engineering_candidate_controlled_file_content_mismatch")
    return observation


def _build(probe, storage_ref, candidate, input_ref, report):
    task_id = candidate.snapshot.binding.task_id
    task = probe.get(f"/api/tasks/{task_id}", TaskView)
    files, _ = candidate_files(storage_ref, candidate)
    definitions = import_module("services.dev-runner.engineering_definition")
    report["last_stage"] = "build_input_definition"
    definition = definitions.definition_for_candidate(files, task.declaration.acceptance_assets_ref)
    report["last_stage"] = "build_http_acceptance"
    accepted = probe.post(f"/api/tasks/{task_id}/builds", RequestBuildRequest(
        expected_version=task.version, expected_control_revision=task.control_revision,
        expected_input_validity_revision=task.input_validity_revision, candidate_id=candidate.snapshot.candidate_id,
        input_set_ref=input_ref, definition=definition,
    ), BuildCommandResult, expected=202)
    require(accepted.outcome == "accepted", "engineering_build_not_accepted")
    workflow = probe.handoff(accepted)
    result = probe.wait(f"/api/tasks/{task_id}/builds/{accepted.operation_id}", BuildView,
        lambda value: value.state == "succeeded", workflow_id=workflow, timeout=900)
    require(result.content_verified and result.content is not None and result.execution is not None
            and result.content.applicable and result.execution.applicable
            and result.execution.observation.closure == "ended_reconciled"
            and result.execution.observation.exit_code == 0
            and result.record.fixed_inputs.candidate == candidate.snapshot
            and result.record.fixed_inputs.definition == definition,
            "engineering_build_has_no_applicable_candidate_bound_physical_result")
    require(len(result.content.artifacts) == 3
            and {item.role for item in result.content.artifacts} == {"frontend", "backend", "postgres"},
            "engineering_build_three_artifacts_missing")
    return result


def _input_reference(build):
    fixed = build.record.fixed_inputs.input_set
    return EngineeringRef(kind="input_set", object_id=fixed.input_set_id, revision="p1-build-fixed-input-r1",
        authority="delivery", digest=fixed.set_digest, digest_algorithm="sha256")


def build_and_environment(probe, storage_ref, candidate, input_ref, report):
    build = _build(probe, storage_ref, candidate, input_ref, report)
    probe.evidence["build"] = build.model_dump(mode="json")
    report["last_stage"] = "three_artifact_environment"
    assets = load_reference_assets(ROOT)
    spec = ArtifactEnvironmentSpec(operation_id="artifact-env-" + uuid4().hex,
        source_revision=candidate.snapshot.candidate_commit, input_set_ref=_input_reference(build),
        storage_ref=storage_ref, acceptance_bundle_digest=assets.bundle_digest,
        deadline=datetime.now(UTC) + timedelta(minutes=15))
    registration = registry_module.EngineeringRegistration(storage=storage_ref)
    registry = registry_module.EngineeringRegistry(registration)
    method = import_module("scripts.p1.check_artifact_environment")
    with registry.admit(2 * 1024**3) as storage, ExitStack() as resources:
        store = resources.enter_context(ArtifactStore(storage.archive_root / "artifacts"))
        applications = {}
        for record in build.content.artifacts:
            content = store.query(record.storage_id)
            require(content.archive_digest == record.archive_digest
                    and content.manifest.digest == record.manifest_digest
                    and content.config.digest == record.config_digest
                    and content.image_id == record.image_id and content.platform == record.platform,
                    "engineering_environment_artifact_differs_from_build")
            applications[record.role] = (store, content)
        result = method.run(storage.admission, spec, applications, repository=ROOT,
                            input_binding="candidate_bound_build_input_set")
        probe.evidence["artifact_environment"] = result
        require(result.get("result") == "passed" and result.get("disposed", {}).get("state") == "disposed",
                "engineering_artifact_environment_failed")
        observed = result.get("artifact_set", {})
        for role, (_, content) in applications.items():
            require(observed.get(role, {}).get("archive_digest") == content.archive_digest,
                    "engineering_environment_replaced_a_build_artifact")
        probe.evidence["storage_after_environment"] = storage.observe().model_dump(mode="json")
