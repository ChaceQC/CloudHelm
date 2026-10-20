"""Real HTTP, Workspace and Runner method for the mutable P1.2 dev profile."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.development_environment import WorkspaceDevelopmentEnvironmentObservation
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.workspace_git import content_digest
from packages.contracts.p1.workspace_requests import WorkspaceView
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture
from scripts.p1.development_storage_pin_checks import (
    verify_container_recovery_guard,
    verify_storage_pin,
)
from scripts.p1.engineering_chain import (
    accept_source,
    grant_engineering,
    materialize,
    reference_task,
)
from scripts.p1.engineering_fixture import (
    ENGINEERING_ACTIONS,
    PROJECT,
    EngineeringCheckFailure,
    EngineeringProbe,
    ROOT,
    fixed_inputs,
    process_fixture,
    require,
)
from scripts.p1.engineering_physical import candidate_files
from scripts.p1.runtime_processes import RuntimeProcessError, api_running, worker_running
from scripts.p1.workspace_development_fixture import (
    DEVELOPMENT_DATA_R2,
    DEV_MARKER_PATH,
    DEV_MARKER_R1,
    DEV_MARKER_R2,
    LOCK_PATH,
    WorkspaceDevelopmentCheckFailure,
    create_synthetic_note,
    development_environment,
    fixed_reference_file,
    freeze_workspace_candidate,
    initial_devmarker_source,
    mutate_workspace_file,
    replace_devmarker_source,
    submit_control,
    submit_prepare,
    wait_development_operation,
    workspace_file,
)

METHOD_REVISION = "p1-2-workspace-development-r4"
NOTE_TITLE_PREFIX = "cloudhelm-p1-workspace-reset-"
NOTE_BODY = "Disposable Workspace development reset probe."
LOCK_COMMENT_VARIANT = importlib.import_module(
    "services.dev-runner.workspace_development_inputs"
).LOCK_COMMENT_VARIANT


def _environment() -> dict:
    require(
        os.name == "posix"
        and os.environ.get("WSL_DISTRO_NAME") == "Ubuntu-24.04"
        and os.getuid() == 1000
        and ROOT == Path("/mnt/e/Project/CloudHelm"),
        "workspace_development_requires_registered_wsl_checkout_and_uid",
    )
    return {
        "distribution": "Ubuntu-24.04",
        "kernel": platform.release(),
        "uid": os.getuid(),
        "repository": str(ROOT),
        "mount_namespace": os.readlink("/proc/self/ns/mnt"),
        "python": platform.python_version(),
        "interpreter": sys.executable,
    }


def _workspace_view(probe: EngineeringProbe, workspace_id: str) -> WorkspaceView:
    return probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)


def _require_ready(probe, environment_id: str, operation, binding, source_digest: str):
    view = development_environment(probe, environment_id)
    observation = view.latest_observation
    require(view.state == "ready" and observation is not None and observation.state == "ready",
            "workspace_development_environment_not_ready")
    require(observation.operation_id == operation.result.operation_id
            and observation.binding == binding
            and observation.source_manifest_digest == source_digest
            and observation.runtime_fact is not None
            and observation.runtime_fact.status == "running"
            and observation.health_probe is not None and observation.health_probe.outcome == "passed"
            and observation.ready_probe is not None and observation.ready_probe.outcome == "passed",
            "workspace_development_ready_observation_mismatch")
    return view, observation


def _method_runtime(probe: EngineeringProbe, storage_ref: DevelopmentStorageRef):
    registry_module = importlib.import_module("services.dev-runner.engineering_registry")
    worker_module = importlib.import_module("services.hub-worker.engineering_runtime")
    registration = registry_module.EngineeringRegistration(storage=storage_ref)
    return worker_module.create_engineering_runtime(probe.pools, registration=registration)


def _controller(runtime, operation_id: str):
    return runtime.development_controller_for(operation_id)


def _dependency_evidence(controller, operation_id: str) -> dict:
    value = controller.dependency_evidence(operation_id)
    required = {"reused", "environment_key", "lock_digest", "dependency_cache_key",
                "toolchain_digest", "snapshot_digest", "snapshot_bytes"}
    require(type(value) is dict and required.issubset(value),
            "workspace_development_dependency_evidence_missing")
    safe = {key: value[key] for key in sorted(required)}
    import re

    require(type(safe["reused"]) is bool
            and re.fullmatch(r"[0-9a-f]{64}", safe["environment_key"]) is not None
            and all(isinstance(safe[key], str)
                    and re.fullmatch(r"sha256:[0-9a-f]{64}", safe[key]) is not None
                    for key in ("lock_digest", "toolchain_digest", "dependency_cache_key", "snapshot_digest"))
            and type(safe["snapshot_bytes"]) is int and safe["snapshot_bytes"] > 0,
            "workspace_development_dependency_evidence_invalid")
    return safe


def _controller_probe(runtime, operation_id: str, storage_ref: DevelopmentStorageRef, binding,
                      name: str) -> dict:
    controller = _controller(runtime, operation_id)
    with runtime.registry.admit(0) as storage:
        result = getattr(controller, name)(storage, binding)
        storage.observe()
    require(type(result) is dict, "workspace_development_probe_result_invalid")
    return result


def _registered_readers(runtime, binding):
    readers = runtime._development.registered_readers(binding)
    require(isinstance(readers, tuple) and bool(readers), "workspace_development_live_reader_missing")
    return readers


def _probe_notes(runtime, operation_id: str, storage_ref: DevelopmentStorageRef, binding) -> dict:
    value = _controller_probe(runtime, operation_id, storage_ref, binding, "probe_notes")
    require(value.get("source_manifest_digest") is not None
            and isinstance(value.get("notes"), list) and len(value["notes"]) <= 256,
            "workspace_development_notes_probe_invalid")
    return value


def _note_title_digest(title: str) -> str:
    return content_digest(title.encode("utf-8"))


def _find_note(notes: dict, title: str) -> bool:
    expected = _note_title_digest(title)
    return any(item.get("title_digest") == expected for item in notes["notes"] if isinstance(item, dict))


def _workspace_dependency_cache_keys(runtime, binding) -> tuple[str, ...]:
    import re
    import stat
    import rfc8785

    with runtime.registry.admit(0) as storage:
        path = Path(storage.cache_root) / "workspace-python"
        namespace = hashlib.sha256(rfc8785.dumps([binding.project_id, binding.workspace_id])).hexdigest()
        for directory in (path, path / namespace):
            try:
                before = directory.lstat()
            except FileNotFoundError:
                return ()
            if (not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode)
                    or before.st_uid != os.getuid() or before.st_mode & 0o077
                    or before.st_dev != os.fstat(storage.admission.directory_fd).st_dev):
                raise WorkspaceDevelopmentCheckFailure("workspace_development_cache_directory_invalid")
        path = path / namespace
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            state = os.fstat(descriptor)
            names = tuple(sorted(os.listdir(descriptor)))
            if ((state.st_dev, state.st_ino) != (before.st_dev, before.st_ino)
                    or len(names) > 32
                    or any(re.fullmatch(r"[0-9a-f]{64}", name) is None for name in names)):
                raise WorkspaceDevelopmentCheckFailure("workspace_development_cache_inventory_invalid")
        finally:
            os.close(descriptor)
        storage.observe()
    return names


def _run_method(args, report: dict) -> None:
    environment = report["environment"]
    storage_ref = DevelopmentStorageRef(
        storage_id=args.storage_id,
        instance_revision=args.storage_revision,
        purpose="workspace",
    )
    storage_module = importlib.import_module("services.dev-runner.development_storage")
    storage_owner = storage_module.DevelopmentStorage(storage_ref.storage_id)
    with storage_owner.admit_ref(storage_ref, requested_bytes=0) as admission:
        report["storage_before"] = admission.observe().model_dump(mode="json")
    report["storage_pin_check"] = verify_storage_pin(storage_ref)

    database_failure = None
    process_failure = None
    pending = None
    database_opened = False
    process_cleanup = "not_started"
    probe = None
    method_runtime = None
    try:
        with database_fixture(port=args.port) as base_fixture:
            database_opened = True
            fixture = process_fixture(base_fixture, storage_ref)
            probe = EngineeringProbe(fixture)
            try:
                probe.open()
                try:
                    with api_running(probe.fixture, instance="workspace") as api:
                        probe.http = api.client
                        with worker_running(probe.fixture) as worker:
                            report["database_fixture"] = {
                                "project_name": base_fixture.project_name,
                                "port": base_fixture.port,
                                "installation_id": base_fixture.baseline.installation_id,
                                "isolated_new_database": True,
                            }
                            report["worker"] = {
                                "pid": worker.process.pid,
                                "installation_id": worker.installation_id,
                                "instances_started_by_method": 1,
                            }
                            try:
                                method_runtime = _method_runtime(probe, storage_ref)
                                _run_workspace_chain(probe, method_runtime, storage_ref, report)
                                process_cleanup = "complete"
                            except Exception as failure:
                                pending = failure
                                process_cleanup = "unconfirmed" if isinstance(failure, RuntimeProcessError) else "complete"
                except Exception as failure:
                    pending = pending or failure
                    process_cleanup = "unconfirmed"
            except Exception as failure:
                pending = pending or failure
                process_cleanup = "unconfirmed"
            finally:
                if method_runtime is not None:
                    try:
                        method_runtime.close()
                    except Exception as failure:
                        pending = pending or failure
                        process_cleanup = "unconfirmed"
                if probe is not None:
                    try:
                        probe.close()
                    except Exception as failure:
                        pending = pending or failure
                        process_cleanup = "unconfirmed"
        report["database_and_process_cleanup"] = "complete"
        if pending is not None:
            raise pending
    except DatabaseFixtureError as failure:
        database_failure = failure
        report["database_and_process_cleanup"] = "unconfirmed"
        raise
    finally:
        report["process_cleanup"] = process_cleanup
        if "database_and_process_cleanup" not in report:
            report["database_and_process_cleanup"] = "unconfirmed" if database_opened else "not_started"
        report["database_cleanup"] = (
            "complete" if report["database_and_process_cleanup"] == "complete" and database_failure is None
            else "unconfirmed" if database_opened else "not_started"
        )
        try:
            with storage_owner.admit_ref(storage_ref, requested_bytes=0) as admission:
                report["storage_after"] = admission.observe().model_dump(mode="json")
        except Exception:
            report["storage_after"] = None
            report["storage_after_observation"] = "unavailable"
        disposed = report.get("dispose_confirmed") is True
        report["database_and_process_cleanup"] = (
            "complete" if process_cleanup == "complete" and database_failure is None
            and report.get("database_and_process_cleanup") == "complete" else "unconfirmed"
        )
        report["storage_release_safe"] = bool(
            report["database_and_process_cleanup"] == "complete"
            and report.get("storage_after") is not None
            and disposed
        )


def _run_workspace_chain(probe: EngineeringProbe, runtime, storage_ref: DevelopmentStorageRef,
                         report: dict) -> None:
    from scripts.p1.engineering_chain import operation
    from scripts.p1.engineering_physical import candidate_files
    from scripts.p1.workspace_development_fixture import (
        freeze_workspace_candidate,
        submit_control,
        submit_prepare,
        wait_development_operation,
    )

    report["last_stage"] = "real_http_source_task_workspace"
    grant_engineering(probe)
    source, workflow = accept_source(probe)
    active, input_ref = reference_task(probe, source, workflow)
    workspace_id, initial_manifest, _, _ = materialize(probe, active, input_ref)

    main_original = fixed_reference_file("app/main.py")
    lock_original = importlib.import_module("services.dev-runner.python_dependencies").reference_inputs()["uv.lock"]
    require(main_original and lock_original, "workspace_development_fixed_source_missing")
    main_r1 = initial_devmarker_source(main_original)
    main_original_record = workspace_file(DEV_MARKER_PATH, main_original)
    lock_original_record = workspace_file(LOCK_PATH, lock_original)
    manifest_r1, main_r1_record, source_mutation_r1 = mutate_workspace_file(
        probe, workspace_id, input_ref, initial_manifest, DEV_MARKER_PATH, main_r1, main_original_record,
    )
    report["workspace_mutations"] = [{
        "operation_id": source_mutation_r1.operation_id,
        "path": DEV_MARKER_PATH,
        "before_manifest_digest": source_mutation_r1.before_manifest_digest,
        "after_manifest_digest": source_mutation_r1.after_manifest_digest,
    }]

    report["last_stage"] = "http_prepare_and_runner_ready"
    prepare = submit_prepare(probe, workspace_id, input_ref)
    environment_id = prepare.environment_id
    require(environment_id is not None, "workspace_development_prepare_environment_id_missing")
    prepare_operation = wait_development_operation(probe, prepare, "succeeded")
    workspace = _workspace_view(probe, workspace_id)
    binding_r1 = workspace.workspace.binding
    source_observer = importlib.import_module("services.dev-runner.workspace_development_source")
    with runtime.registry.admit(0) as storage:
        observed_r1 = source_observer.observe_workspace_source(storage, binding_r1)
    _, observation_r1 = _require_ready(
        probe, environment_id, prepare_operation, binding_r1, observed_r1.manifest_digest,
    )
    require(observed_r1.manifest_digest == manifest_r1
            and observation_r1.data_revision == "reference-synthetic-r1",
            "workspace_development_prepare_source_or_data_revision_mismatch")
    report["prepare_observation"] = observation_r1.model_dump(mode="json")
    report["operation_ids"] = {"prepare": prepare.operation_id}
    dependency_a_first = _dependency_evidence(_controller(runtime, prepare.operation_id), prepare.operation_id)
    require(not dependency_a_first["reused"] and dependency_a_first["lock_digest"] == content_digest(lock_original),
            "workspace_development_original_lock_was_not_installed_once")
    report["dependency_evidence"] = {"original_lock_first_prepare": dependency_a_first}
    report["storage_pin_check_live"] = verify_container_recovery_guard(storage_ref)

    marker_probe_r1 = _controller_probe(runtime, prepare.operation_id, storage_ref, binding_r1, "probe_devmarker")
    require(marker_probe_r1.get("status") == 200
            and marker_probe_r1.get("source_manifest_digest") == observed_r1.manifest_digest,
            "workspace_development_devmarker_route_not_served")
    report["http_probes"] = {"devmarker_r1": marker_probe_r1}

    readers_r1 = _registered_readers(runtime, binding_r1)
    backend_readers = [item for item in readers_r1
                       if item.method == "p1-workspace-development-r1" and item.mount_destination == "/workspace"]
    require(bool(backend_readers), "workspace_development_backend_reader_not_registered")
    title = NOTE_TITLE_PREFIX + uuid4().hex
    created_note = create_synthetic_note(backend_readers[0].container_id, title, NOTE_BODY)
    notes_r1 = _probe_notes(runtime, prepare.operation_id, storage_ref, binding_r1)
    require(_find_note(notes_r1, title), "workspace_development_http_note_missing_before_suspend")
    report["http_probes"]["notes_before_suspend"] = {
        "response_digest": notes_r1["response_digest"],
        "synthetic_note_title_digest": _note_title_digest(title),
        "synthetic_note_id": created_note["id"],
    }

    report["last_stage"] = "live_reader_candidate_freeze"
    candidate, candidate_receipt = freeze_workspace_candidate(probe, workspace_id, input_ref, manifest_r1)
    frozen_files, frozen_observation = candidate_files(storage_ref, candidate)
    require(frozen_files.get(DEV_MARKER_PATH) == main_r1
            and frozen_files.get(LOCK_PATH) == lock_original
            and candidate_receipt.writer_scope_digest.startswith("sha256:")
            and candidate_receipt.runtime_scope_id,
            "workspace_development_live_reader_candidate_not_fixed")
    report["live_reader_candidate"] = {
        "candidate_id": candidate.snapshot.candidate_id,
        "freeze_operation_id": candidate.snapshot.freeze_operation_id,
        "manifest_digest": candidate.snapshot.manifest_digest,
        "writer_scope_digest": candidate_receipt.writer_scope_digest,
        "runtime_scope_id": candidate_receipt.runtime_scope_id,
        "live_readers": [item.model_dump(mode="json") for item in readers_r1],
        "candidate_observation": frozen_observation,
    }

    report["last_stage"] = "live_source_mutation_and_http_refresh"
    main_r2 = replace_devmarker_source(main_r1)
    manifest_r2, main_r2_record, source_mutation_r2 = mutate_workspace_file(
        probe, workspace_id, input_ref, manifest_r1, DEV_MARKER_PATH, main_r2, main_r1_record,
    )
    report["workspace_mutations"].append({
        "operation_id": source_mutation_r2.operation_id,
        "path": DEV_MARKER_PATH,
        "before_manifest_digest": source_mutation_r2.before_manifest_digest,
        "after_manifest_digest": source_mutation_r2.after_manifest_digest,
    })
    refresh = submit_control(probe, workspace_id, environment_id, input_ref, "resume")
    refresh_operation = wait_development_operation(probe, refresh, "succeeded")
    binding_r2 = _workspace_view(probe, workspace_id).workspace.binding
    with runtime.registry.admit(0) as storage:
        observed_r2 = source_observer.observe_workspace_source(storage, binding_r2)
    _, observation_r2 = _require_ready(
        probe, environment_id, refresh_operation, binding_r2, observed_r2.manifest_digest,
    )
    marker_probe_r2 = _controller_probe(runtime, refresh.operation_id, storage_ref, binding_r2, "probe_devmarker")
    require(observed_r2.manifest_digest == manifest_r2
            and marker_probe_r2.get("status") == 200
            and marker_probe_r2.get("source_manifest_digest") == observed_r2.manifest_digest
            and marker_probe_r2.get("response_digest") != marker_probe_r1.get("response_digest"),
            "workspace_development_live_source_change_not_observed_over_http")
    report["http_probes"]["devmarker_r2"] = marker_probe_r2
    report["source_refresh"] = {
        "binding": observation_r2.binding.model_dump(mode="json"),
        "workspace_manifest_digest": observed_r2.manifest_digest,
        "runner_manifest_digest": observation_r2.source_manifest_digest,
        "candidate_manifest_digest": candidate.snapshot.manifest_digest,
        "candidate_stayed_on_r1": candidate.snapshot.manifest_digest == manifest_r1,
    }
    current_candidate_files, current_candidate_observation = candidate_files(storage_ref, candidate)
    require(current_candidate_observation["manifest_digest"] == candidate.snapshot.manifest_digest
            and current_candidate_files.get(DEV_MARKER_PATH) == main_r1
            and current_candidate_files.get(LOCK_PATH) == lock_original,
            "workspace_development_mutation_changed_frozen_candidate")

    report["last_stage"] = "suspend_resume_data_retention_and_same_lock_cache"
    suspend = submit_control(probe, workspace_id, environment_id, input_ref, "suspend")
    suspend_operation = wait_development_operation(probe, suspend, "succeeded")
    suspend_observation = suspend_operation.observation
    require(suspend_observation is not None and suspend_observation.state == "suspended"
            and suspend_observation.stop_fact is not None
            and suspend_observation.stop_fact.outcome == "confirmed_stopped",
            "workspace_development_suspend_physical_stop_missing")
    resume_a = submit_control(probe, workspace_id, environment_id, input_ref, "resume")
    resume_a_operation = wait_development_operation(probe, resume_a, "succeeded")
    binding_resume_a = _workspace_view(probe, workspace_id).workspace.binding
    with runtime.registry.admit(0) as storage:
        observed_resume_a = source_observer.observe_workspace_source(storage, binding_resume_a)
    _, observation_resume_a = _require_ready(
        probe, environment_id, resume_a_operation, binding_resume_a, observed_resume_a.manifest_digest,
    )
    dependency_a_reused = _dependency_evidence(_controller(runtime, resume_a.operation_id), resume_a.operation_id)
    notes_after_resume_a = _probe_notes(runtime, resume_a.operation_id, storage_ref, binding_resume_a)
    require(dependency_a_reused["reused"]
            and dependency_a_reused["environment_key"] == dependency_a_first["environment_key"]
            and dependency_a_reused["lock_digest"] == dependency_a_first["lock_digest"]
            and observation_resume_a.data_generation == observation_r2.data_generation
            and _find_note(notes_after_resume_a, title),
            "workspace_development_same_lock_resume_or_data_retention_failed")
    report["dependency_evidence"]["original_lock_resume"] = dependency_a_reused
    report["operation_ids"].update({"source_refresh": refresh.operation_id,
                                    "suspend": suspend.operation_id,
                                    "same_lock_resume": resume_a.operation_id})
    report["suspend_resume"] = {
        "suspend_operation_id": suspend.operation_id,
        "confirmed_stopped": True,
        "resume_operation_id": resume_a.operation_id,
        "data_generation_preserved": observation_resume_a.data_generation == observation_r2.data_generation,
        "synthetic_note_retained": _find_note(notes_after_resume_a, title),
        "resume_observation": observation_resume_a.model_dump(mode="json"),
    }

    report["last_stage"] = "synthetic_data_revision_reset"
    reset = submit_control(probe, workspace_id, environment_id, input_ref, "reset_data",
                           target_data_revision=DEVELOPMENT_DATA_R2)
    reset_operation = wait_development_operation(probe, reset, "succeeded")
    binding_reset = _workspace_view(probe, workspace_id).workspace.binding
    require(reset_operation.observation is not None, "workspace_development_reset_observation_missing")
    _, observation_reset = _require_ready(
        probe, environment_id, reset_operation, binding_reset, reset_operation.observation.source_manifest_digest,
    )
    notes_after_reset = _probe_notes(runtime, reset.operation_id, storage_ref, binding_reset)
    title_r1 = "CloudHelm synthetic seed reference-synthetic-r1"
    title_r2 = "CloudHelm synthetic seed reference-synthetic-r2"
    require(observation_reset.data_revision == DEVELOPMENT_DATA_R2
            and observation_reset.data_generation == observation_resume_a.data_generation + 1
            and not _find_note(notes_after_reset, title)
            and not _find_note(notes_after_reset, title_r1)
            and _find_note(notes_after_reset, title_r2),
            "workspace_development_data_reset_revision_or_contents_mismatch")
    report["data_reset"] = {
        "operation_id": reset.operation_id,
        "from_revision": observation_resume_a.data_revision,
        "to_revision": observation_reset.data_revision,
        "generation_before": observation_resume_a.data_generation,
        "generation_after": observation_reset.data_generation,
        "old_user_note_removed": True,
        "old_seed_removed": True,
        "new_revision_seed_present": True,
        "notes_response_digest": notes_after_reset["response_digest"],
    }
    report["operation_ids"]["reset_data"] = reset.operation_id

    report["last_stage"] = "fixed_lock_variant_cache_invalidation"
    lock_variant = lock_original + LOCK_COMMENT_VARIANT
    manifest_b, lock_b_record, lock_mutation_b = mutate_workspace_file(
        probe, workspace_id, input_ref, manifest_r2, LOCK_PATH, lock_variant, lock_original_record,
    )
    report["workspace_mutations"].append({
        "operation_id": lock_mutation_b.operation_id,
        "path": LOCK_PATH,
        "before_manifest_digest": lock_mutation_b.before_manifest_digest,
        "after_manifest_digest": lock_mutation_b.after_manifest_digest,
    })
    suspend_b = submit_control(probe, workspace_id, environment_id, input_ref, "suspend")
    suspend_b_operation = wait_development_operation(probe, suspend_b, "succeeded")
    require(suspend_b_operation.observation is not None
            and suspend_b_operation.observation.stop_fact is not None
            and suspend_b_operation.observation.stop_fact.outcome == "confirmed_stopped",
            "workspace_development_lock_change_suspend_not_confirmed")
    resume_b = submit_control(probe, workspace_id, environment_id, input_ref, "resume")
    resume_b_operation = wait_development_operation(probe, resume_b, "succeeded")
    binding_b = _workspace_view(probe, workspace_id).workspace.binding
    with runtime.registry.admit(0) as storage:
        observed_b = source_observer.observe_workspace_source(storage, binding_b)
    _, observation_b = _require_ready(probe, environment_id, resume_b_operation, binding_b, observed_b.manifest_digest)
    dependency_b = _dependency_evidence(_controller(runtime, resume_b.operation_id), resume_b.operation_id)
    require(not dependency_b["reused"]
            and dependency_b["lock_digest"] == content_digest(lock_variant)
            and dependency_b["environment_key"] != dependency_a_first["environment_key"]
            and observed_b.manifest_digest == manifest_b,
            "workspace_development_lock_variant_did_not_invalidate_cache")
    cache_keys_after_b = _workspace_dependency_cache_keys(runtime, binding_b)
    require(set(cache_keys_after_b) == {
        dependency_a_first["environment_key"], dependency_b["environment_key"],
    }, "workspace_development_lock_cache_entry_set_mismatch")
    report["dependency_evidence"]["approved_lock_comment_variant"] = dependency_b
    report["operation_ids"].update({"suspend_before_lock_variant": suspend_b.operation_id,
                                    "approved_lock_variant_resume": resume_b.operation_id})

    report["last_stage"] = "unknown_lock_refusal_before_install"
    lock_unknown = lock_original + b"# CloudHelm unapproved development lock change\n"
    manifest_unknown, _, lock_mutation_unknown = mutate_workspace_file(
        probe, workspace_id, input_ref, manifest_b, LOCK_PATH, lock_unknown, lock_b_record,
    )
    report["workspace_mutations"].append({
        "operation_id": lock_mutation_unknown.operation_id,
        "path": LOCK_PATH,
        "before_manifest_digest": lock_mutation_unknown.before_manifest_digest,
        "after_manifest_digest": lock_mutation_unknown.after_manifest_digest,
    })
    suspend_unknown = submit_control(probe, workspace_id, environment_id, input_ref, "suspend")
    suspend_unknown_operation = wait_development_operation(probe, suspend_unknown, "succeeded")
    require(suspend_unknown_operation.observation is not None
            and suspend_unknown_operation.observation.stop_fact is not None
            and suspend_unknown_operation.observation.stop_fact.outcome == "confirmed_stopped",
            "workspace_development_unknown_lock_suspend_not_confirmed")
    resume_unknown = submit_control(probe, workspace_id, environment_id, input_ref, "resume", expected_status=409)
    require(resume_unknown.outcome == "rejected" and resume_unknown.operation_id is None,
            "workspace_development_unknown_lock_not_rejected")
    cache_keys_after_unknown = _workspace_dependency_cache_keys(runtime, binding_b)
    require(set(cache_keys_after_unknown) == set(cache_keys_after_b),
            "workspace_development_unknown_lock_created_cache_entry")
    report["unknown_lock"] = {
        "command_id": resume_unknown.command_id,
        "manifest_digest": manifest_unknown,
        "failure_code": resume_unknown.code,
        "cache_keys_unchanged": True,
    }
    report["operation_ids"]["suspend_before_unknown_lock"] = suspend_unknown.operation_id

    report["last_stage"] = "http_dispose_and_storage_retention"
    dispose = submit_control(probe, workspace_id, environment_id, input_ref, "dispose")
    dispose_operation = wait_development_operation(probe, dispose, "succeeded")
    disposed = dispose_operation.observation
    require(disposed is not None and disposed.state == "disposed"
            and disposed.stop_fact is not None
            and disposed.stop_fact.outcome == "confirmed_stopped",
            "workspace_development_dispose_physical_stop_missing")
    _check_disposed_containers(environment_id)
    after_files, after_candidate = candidate_files(storage_ref, candidate)
    require(after_candidate["manifest_digest"] == candidate.snapshot.manifest_digest
            and after_files.get(DEV_MARKER_PATH) == main_r1
            and after_files.get(LOCK_PATH) == lock_original,
            "workspace_development_dispose_changed_retained_candidate")
    report["dispose_confirmed"] = True
    report["dispose"] = {
        "operation_id": dispose.operation_id,
        "confirmed_stopped": True,
        "containers_removed": True,
        "candidate_storage_retained_until_wrapper_cleanup": True,
        "candidate_manifest_digest": candidate.snapshot.manifest_digest,
    }
    report["operation_ids"]["dispose"] = dispose.operation_id
    require(_workspace_dependency_cache_keys(runtime) == cache_keys_after_b,
            "workspace_development_dispose_removed_retained_dependency_cache")
    report["required_checks"] = {
        "approved_source_mutation_visible_over_http": True,
        "same_lock_reused_and_fixed_variant_invalidated": True,
        "suspend_resume_physical_stop_and_data_retention": True,
        "synthetic_revision_r1_to_r2_rebuilt": True,
        "live_reader_candidate_frozen_across_edits": True,
        "dispose_stopped_and_storage_retained": True,
    }
    report["final_environment"] = disposed.model_dump(mode="json")


def _check_disposed_containers(environment_id: str) -> None:
    docker_module = importlib.import_module("services.dev-runner.artifact_environment_docker")
    result = docker_module.docker(
        "ps", "--all", "--quiet", "--no-trunc",
        "--filter", "label=cloudhelm.environment_id=" + environment_id,
    )
    if len(result.stdout) > 65536:
        raise WorkspaceDevelopmentCheckFailure("workspace_development_container_inventory_exceeded")
    require(not result.stdout.strip(), "workspace_development_dispose_left_environment_containers")


def _public_input(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "files"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--development", action="store_true")
    mode.add_argument("--input-set")
    parser.add_argument("--storage-id", required=True)
    parser.add_argument("--storage-revision", required=True)
    parser.add_argument("--port", type=int, default=55439)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = {
        "method_revision": METHOD_REVISION,
        "method_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "status": "failed",
        "complete_scope": False,
        "human_acceptance": None,
        "p1_2_stage_acceptance": False,
        "mode": "development_worktree" if args.development else "fixed_input_set",
        "scope": "real_source_task_workspace_mutable_development_environment_lifecycle",
        "support_scope": "one WSL Ubuntu-24.04 local controlled development fixture; no Desktop or remote delivery",
        "database_and_process_cleanup": "not_started",
        "storage_release_safe": False,
    }
    before = None
    try:
        report["environment"] = _environment()
        before = fixed_inputs(args.input_set)
        report["input_before"] = _public_input(before)
        _run_method(args, report)
        report["status"] = "passed"
    except (EngineeringCheckFailure, WorkspaceDevelopmentCheckFailure) as failure:
        report.update(status="failed", failure_code=str(failure))
    except DatabaseFixtureError as failure:
        report.update(status="failed", failure_code=str(failure))
        if getattr(failure, "public_diagnostic", None):
            report["diagnostic"] = failure.public_diagnostic
    except RuntimeProcessError as failure:
        report.update(status="failed", failure_code=str(failure), database_and_process_cleanup="unconfirmed",
                      storage_release_safe=False)
    except Exception as failure:
        report.update(status="failed", failure_code="workspace_development_method_failed",
                      failure_type=type(failure).__name__)
        report["failure_location"] = [
            {"file": Path(item.filename).name, "line": item.lineno, "function": item.name}
            for item in traceback.extract_tb(failure.__traceback__)[-6:]
        ]
    finally:
        if before is not None:
            try:
                after = fixed_inputs(args.input_set)
                report["input_after"] = _public_input(after)
                report["public_inputs_unchanged"] = before == after
                require(before == after, "workspace_development_public_input_changed_during_run")
            except Exception:
                report.update(status="failed", failure_code="workspace_development_input_postcheck_failed",
                              public_inputs_unchanged=False, storage_release_safe=False)
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8", newline="\n") as output:
                output.write(encoded)
        except OSError:
            report.update(status="failed", failure_code="workspace_development_report_not_saved",
                          storage_release_safe=False)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
