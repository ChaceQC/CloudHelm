"""Durable, gated lifecycle control for mutable Workspace development environments."""

from __future__ import annotations

import importlib
import os
import re
import stat
import threading
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from modules.workspaces.candidate_writers import overlaps
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError
from packages.contracts.p1.development_environment import (
    PrepareWorkspaceDevelopmentEnvironment,
    ResetWorkspaceDevelopmentData, ResumeWorkspaceDevelopmentEnvironment,
    WorkspaceDevelopmentEnvironmentObservation,
    WorkspaceDevelopmentEnvironmentOperationIntent, WorkspaceDevelopmentEnvironmentSpec,
    WorkspaceDevelopmentRuntimeFact, WorkspaceDevelopmentStopFact,
)
from packages.contracts.p1.workspace_candidates import RegisteredWorkspaceReader, workspace_runtime_scope_id
from packages.contracts.p1.workspace_git import WorkspaceBinding

from .toolchain import ProbeFailure
from .workspace_development_inputs import workspace_storage_id
from .workspace_development_journal import (
    JOURNAL_SCHEMA, MAX_ENVIRONMENT_OPERATIONS, WorkspaceDevelopmentJournal,
    observation as _observation, observation_digest as _observation_digest,
    operation_intent as _operation_intent, validated_intent as _validated_intent,
)
from .workspace_development_recipe import DATASET_REVISIONS
from .workspace_development_source import observe_workspace_source

_TARGET_STATE = {"prepare": "ready", "suspend": "suspended", "resume": "ready",
                 "reset_data": "ready", "dispose": "disposed"}
_ALLOWED_STATE = {
    "suspend": {"ready", "failed", "preparing"},
    "resume": {"suspended", "failed", "ready"},
    "reset_data": {"ready", "suspended", "failed"},
    "dispose": {"preparing", "ready", "suspended", "failed"},
}
_MAX_RUNTIME_ENVIRONMENTS = 32
_MAX_DELETE_ENTRIES = 100000
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _failure_code(error: Exception) -> str:
    value = getattr(error, "category", None) or getattr(error, "code", None)
    if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 96:
        return value
    return "workspace_development_" + type(error).__name__.lower()


def _current_spec(base: WorkspaceDevelopmentEnvironmentSpec,
                  request, *, target_generation: int | None = None) -> WorkspaceDevelopmentEnvironmentSpec:
    values = base.model_dump(mode="python")
    values["binding"] = request.binding
    values["source_manifest_digest"] = request.source_manifest_digest
    if type(request) is ResumeWorkspaceDevelopmentEnvironment:
        values.update(request.spec.model_dump(mode="python"))
    elif type(request) is ResetWorkspaceDevelopmentData:
        values["data_revision"] = request.target_data_revision
        values["data_generation"] = request.expected_data_generation + 1
    elif target_generation is not None:
        values["data_generation"] = target_generation
    try:
        return WorkspaceDevelopmentEnvironmentSpec.model_validate(values)
    except (TypeError, ValueError):
        raise ProbeFailure("workspace_development_current_spec_invalid") from None


def _check_registry_storage(registry, reference) -> None:
    configured = getattr(getattr(registry, "registration", None), "storage", None)
    if configured != reference:
        raise ProbeFailure("workspace_development_registry_storage_mismatch")


def _runtime_type():
    try:
        return importlib.import_module("services.dev-runner.workspace_development_runtime").WorkspaceDevelopmentRuntime
    except (ImportError, AttributeError):
        raise ProbeFailure("workspace_development_runtime_unavailable") from None


def _make_runtime(spec: WorkspaceDevelopmentEnvironmentSpec):
    runtime_type = _runtime_type()
    runtime = runtime_type(spec)
    runtime.acquire_storage_pin()
    return runtime


@contextmanager
def _remove_contents(directory: int, *, gate: Callable[[str], None], operation_id: str,
                    device: int, counter: list[int]):
    """Yield after securely unlinking only regular files and directories under an owned root."""
    for name in sorted(os.listdir(directory)):
        if name in {".", ".."} or "/" in name or "\x00" in name:
            raise ProbeFailure("workspace_development_delete_entry_invalid")
        counter[0] += 1
        if counter[0] > _MAX_DELETE_ENTRIES:
            raise ProbeFailure("workspace_development_delete_limit_exceeded")
        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except OSError:
            raise ProbeFailure("workspace_development_delete_inventory_unavailable") from None
        if stat.S_ISDIR(info.st_mode):
            if (info.st_uid != os.geteuid() or info.st_dev != device or info.st_mode & 0o077):
                raise ProbeFailure("workspace_development_delete_directory_unsafe")
            try:
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
            except OSError:
                raise ProbeFailure("workspace_development_delete_directory_unsafe") from None
            try:
                if (os.fstat(child).st_ino != info.st_ino or os.fstat(child).st_dev != device):
                    raise ProbeFailure("workspace_development_delete_directory_changed")
                with _remove_contents(child, gate=gate, operation_id=operation_id,
                                      device=device, counter=counter):
                    pass
            finally:
                os.close(child)
            gate(operation_id)
            try:
                os.rmdir(name, dir_fd=directory)
            except OSError:
                raise ProbeFailure("workspace_development_delete_directory_failed") from None
        elif stat.S_ISREG(info.st_mode):
            if (info.st_uid != os.geteuid() or info.st_dev != device or info.st_mode & 0o077
                    or info.st_nlink != 1):
                raise ProbeFailure("workspace_development_delete_file_unsafe")
            gate(operation_id)
            try:
                os.unlink(name, dir_fd=directory)
            except OSError:
                raise ProbeFailure("workspace_development_delete_file_failed") from None
        else:
            raise ProbeFailure("workspace_development_delete_special_file_forbidden")
    os.fsync(directory)
    yield


def _private_directory(parent: int, name: str, device: int) -> int:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    except OSError:
        raise ProbeFailure("workspace_development_runtime_directory_unavailable") from None
    info = os.fstat(descriptor)
    if (info.st_uid != os.geteuid() or info.st_dev != device or info.st_mode & 0o077):
        os.close(descriptor)
        raise ProbeFailure("workspace_development_runtime_directory_unsafe")
    return descriptor


def _clear_database_directory(runtime, storage, operation_id: str, gate: Callable[[str], None]) -> None:
    expected = storage.workspace_root / "runtime-environments" / runtime.spec.environment_id / "database"
    path = Path(runtime.database_directory) if runtime.database_directory is not None else None
    if path != expected:
        raise ProbeFailure("workspace_development_database_path_mismatch")
    try:
        root = PrivateRoot(storage.workspace_root)
        try:
            device = os.fstat(root.fd).st_dev
            with _open_child(root.fd, "runtime-environments", device) as envs:
                with _open_child(envs, runtime.spec.environment_id, device) as environment:
                    with _open_child(environment, "database", device) as database:
                        gate(operation_id)
                        with _remove_contents(database, gate=gate, operation_id=operation_id,
                                              device=device, counter=[0]):
                            pass
        finally:
            root.close()
    except WorkspaceFileError:
        raise ProbeFailure("workspace_development_database_storage_unavailable") from None


@contextmanager
def _open_child(parent: int, name: str, device: int):
    descriptor = _private_directory(parent, name, device)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _runtime_mounts_absent(storage, environment_path: Path) -> None:
    """Reject deletion while any local Docker container still mounts this environment."""
    try:
        from modules.workspaces.candidate_freeze import _inventory
        for container in _inventory():
            for mount in container["mounts"]:
                source = mount.get("Source", "")
                if source.startswith("/") and overlaps(os.path.realpath(source), str(environment_path)):
                    raise ProbeFailure("workspace_development_runtime_mounts_not_removed")
    except ProbeFailure:
        raise
    except Exception:
        raise ProbeFailure("workspace_development_runtime_mount_inventory_unavailable") from None


def _remove_environment_data(runtime, storage, operation_id: str, gate: Callable[[str], None]) -> bool:
    environment_id = runtime.spec.environment_id
    expected = storage.workspace_root / "runtime-environments" / environment_id
    path = Path(runtime.runtime_directory) if runtime.runtime_directory is not None else None
    if path != expected:
        raise ProbeFailure("workspace_development_runtime_path_mismatch")
    _runtime_mounts_absent(storage, expected)
    try:
        workspace = PrivateRoot(storage.workspace_root)
    except WorkspaceFileError:
        raise ProbeFailure("workspace_development_runtime_root_unavailable") from None
    try:
        device = os.fstat(workspace.fd).st_dev
        with _open_child(workspace.fd, "runtime-environments", device) as runtime_root:
            try:
                environment = os.open(environment_id, _DIRECTORY_FLAGS, dir_fd=runtime_root)
            except FileNotFoundError:
                return True
            except OSError:
                raise ProbeFailure("workspace_development_runtime_directory_unavailable") from None
            try:
                info = os.fstat(environment)
                if (info.st_uid != os.geteuid() or info.st_dev != device or info.st_mode & 0o077):
                    raise ProbeFailure("workspace_development_runtime_directory_unsafe")
                with _remove_contents(environment, gate=gate, operation_id=operation_id,
                                      device=device, counter=[0]):
                    pass
            finally:
                os.close(environment)
            gate(operation_id)
            try:
                os.rmdir(environment_id, dir_fd=runtime_root)
                os.fsync(runtime_root)
            except OSError:
                raise ProbeFailure("workspace_development_runtime_directory_remove_failed") from None
    finally:
        workspace.close()
    storage.observe()
    return True


class WorkspaceDevelopmentController:
    """Persist accepted Runner lifecycle intents and expose only authenticated observations."""

    def __init__(self, registry, gate: Callable[[str], None]):
        if registry is None or not callable(getattr(registry, "admit", None)):
            raise ProbeFailure("workspace_development_engineering_registry_required")
        if not callable(gate):
            raise ProbeFailure("workspace_development_current_gate_required")
        self.registry, self.gate = registry, gate
        self._runtimes: dict[str, object] = {}
        self._mutex = threading.RLock()
        self._closed = False

    @contextmanager
    def _storage(self):
        current = getattr(self.registry, "current_storage", None)
        if callable(current):
            try:
                storage = current()
            except Exception as error:
                if (type(error).__name__ != "EngineeringRegistryError"
                        or str(error) != "engineering_storage_admission_required"):
                    raise
            else:
                yield storage
                return
        with self.registry.admit(0) as storage:
            yield storage

    def _check_ref(self, reference) -> None:
        _check_registry_storage(self.registry, reference)

    def _check_storage(self, storage) -> None:
        try:
            registered = self.registry.registration.storage
            admission = storage.admission
            snapshot = admission.snapshot
            if (registered.storage_id != snapshot.registration.storage_id
                    or registered.instance_revision != snapshot.registration.instance_revision
                    or registered.purpose != snapshot.purpose or snapshot.purpose != "workspace"):
                raise ProbeFailure("workspace_development_registry_storage_mismatch")
            storage.observe()
        except ProbeFailure:
            raise
        except Exception:
            raise ProbeFailure("workspace_development_storage_admission_required") from None

    def _runtime(self, spec: WorkspaceDevelopmentEnvironmentSpec, prepare_operation_id: str):
        self._check_ref(spec.storage_ref)
        with self._mutex:
            if self._closed:
                raise ProbeFailure("workspace_development_controller_closed")
            runtime = self._runtimes.get(spec.environment_id)
            if runtime is not None and getattr(runtime, "prepare_operation_id", None) not in (
                    None, prepare_operation_id):
                raise ProbeFailure("workspace_development_runtime_prepare_identity_mismatch")
            if runtime is None:
                runtime = _make_runtime(spec)
                self._runtimes[spec.environment_id] = runtime
            else:
                runtime.spec = spec
                runtime.binding = spec.binding
                if getattr(runtime, "pin", None) is None:
                    runtime.acquire_storage_pin()
            if runtime.prepare_operation_id is None:
                runtime.prepare_operation_id = prepare_operation_id
            return runtime

    def _prepare_operation(self, session, environment: dict, intent) -> tuple[str, str]:
        request = intent.request
        if type(request) is PrepareWorkspaceDevelopmentEnvironment:
            return request.operation_id, intent.request_digest
        for operation_id in environment.get("operation_ids", []):
            stored = session.read_operation(operation_id)
            if stored is None:
                continue
            previous = _operation_intent(stored, operation_id)
            if type(previous.request) is PrepareWorkspaceDevelopmentEnvironment:
                return operation_id, previous.request_digest
        raise ProbeFailure("workspace_development_prepare_identity_missing")

    def _record_new_intent(self, session, intent: WorkspaceDevelopmentEnvironmentOperationIntent,
                           current_spec: WorkspaceDevelopmentEnvironmentSpec, environment: dict | None) -> dict:
        request = intent.request
        if environment is None:
            if type(request) is not PrepareWorkspaceDevelopmentEnvironment:
                raise ProbeFailure("workspace_development_environment_not_found")
            if request.expected_environment_revision != 0 or intent.accepted_environment_revision != 1:
                raise ProbeFailure("workspace_development_environment_revision_conflict")
            environment = {
                "schema_revision": JOURNAL_SCHEMA, "environment_id": request.environment_id,
                "binding": request.binding.model_dump(mode="json"),
                "source_manifest_digest": request.source_manifest_digest,
                "storage_ref": request.spec.storage_ref.model_dump(mode="json"),
                "spec": request.spec.model_dump(mode="json"),
                "state": "preparing", "physical_state": "unknown",
                "environment_revision": intent.accepted_environment_revision,
                "data_revision": request.spec.data_revision,
                "data_generation": request.spec.data_generation,
                "prepare_operation_id": request.operation_id,
                "latest_operation_id": request.operation_id,
                "latest_request_digest": intent.request_digest,
                "operation_ids": [request.operation_id],
                "pending_operation_id": request.operation_id,
                "created_at": _now(), "updated_at": _now(),
            }
        else:
            if request.action == "prepare":
                raise ProbeFailure("workspace_development_environment_already_exists")
            if request.environment_id != environment.get("environment_id"):
                raise ProbeFailure("workspace_development_environment_scope_mismatch")
            if request.expected_environment_revision != environment.get("environment_revision"):
                raise ProbeFailure("workspace_development_environment_revision_conflict")
            if (request.expected_data_revision != environment.get("data_revision")
                    or request.expected_data_generation != environment.get("data_generation")):
                raise ProbeFailure("workspace_development_data_revision_conflict")
            if environment.get("state") not in _ALLOWED_STATE.get(request.action, set()):
                raise ProbeFailure("workspace_development_state_conflict")
            if environment.get("pending_operation_id"):
                pending = session.read_operation(environment["pending_operation_id"])
                if pending is not None and pending.get("operation_state") in {"pending", "unknown"}:
                    raise ProbeFailure("workspace_development_operation_pending")
            operation_ids = list(environment.get("operation_ids", []))
            if len(operation_ids) >= MAX_ENVIRONMENT_OPERATIONS:
                raise ProbeFailure("workspace_development_journal_operation_limit")
            environment = dict(environment)
            environment.update({
                "binding": request.binding.model_dump(mode="json"),
                "source_manifest_digest": request.source_manifest_digest,
                "spec": current_spec.model_dump(mode="json"),
                "environment_revision": intent.accepted_environment_revision,
                "latest_operation_id": request.operation_id,
                "latest_request_digest": intent.request_digest,
                "pending_operation_id": request.operation_id,
                "updated_at": _now(),
            })
            operation_ids.append(request.operation_id)
            environment["operation_ids"] = operation_ids

        operation = {
            "schema_revision": JOURNAL_SCHEMA, "environment_id": request.environment_id,
            "operation_id": request.operation_id, "action": request.action,
            "request_digest": intent.request_digest, "accepted_environment_revision": intent.accepted_environment_revision,
            "intent": intent.model_dump(mode="json"), "phase": "accepted", "operation_state": "pending",
            "observation_json": None, "observation_digest": None, "failure_code": None,
            "accepted_at": _now(), "updated_at": _now(), "closed_at": None,
        }
        session.write_operation(operation)
        session.write_environment(environment)
        return operation

    def _refresh_environment(self, environment: dict, spec: WorkspaceDevelopmentEnvironmentSpec,
                             observation: WorkspaceDevelopmentEnvironmentObservation,
                             operation_id: str, request_digest: str) -> dict:
        value = dict(environment)
        value.update({
            "binding": observation.binding.model_dump(mode="json"),
            "source_manifest_digest": observation.source_manifest_digest,
            "spec": spec.model_copy(update={"binding": observation.binding,
                "source_manifest_digest": observation.source_manifest_digest,
                "data_revision": observation.data_revision,
                "data_generation": observation.data_generation}).model_dump(mode="json"),
            "state": observation.state, "physical_state": self._physical_state(observation),
            "data_revision": observation.data_revision, "data_generation": observation.data_generation,
            "latest_operation_id": operation_id, "latest_request_digest": request_digest,
            "latest_observation_json": observation.model_dump(mode="json"),
            "latest_observation_digest": _observation_digest(observation), "updated_at": _now(),
        })
        return value

    @staticmethod
    def _physical_state(observation: WorkspaceDevelopmentEnvironmentObservation) -> str:
        if observation.state == "ready":
            return "running"
        if observation.state == "disposed":
            return "removed"
        if observation.state == "suspended":
            return "stopped"
        if observation.state == "failed" and (
                observation.stop_fact is not None and observation.stop_fact.outcome == "confirmed_stopped"
                or observation.runtime_fact is not None and observation.runtime_fact.status == "stopped"):
            return "stopped"
        return "unknown"

    def _validate_observation(self, intent, observation) -> WorkspaceDevelopmentEnvironmentObservation:
        request = intent.request
        if type(observation) is not WorkspaceDevelopmentEnvironmentObservation:
            raise ProbeFailure("workspace_development_observation_unavailable")
        try:
            value = WorkspaceDevelopmentEnvironmentObservation.model_validate(observation.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError):
            raise ProbeFailure("workspace_development_observation_invalid") from None
        if not all((
            value.operation_id == request.operation_id,
            value.request_digest == intent.request_digest,
            value.environment_id == request.environment_id,
            value.binding == request.binding,
            value.storage_ref.purpose == "workspace",
            (request.action in {"suspend", "dispose"}
             or value.source_manifest_digest == request.source_manifest_digest),
        )):
            raise ProbeFailure("workspace_development_observation_binding_mismatch")
        if type(request) is PrepareWorkspaceDevelopmentEnvironment:
            if (value.storage_ref != request.spec.storage_ref or value.migration_revision != request.spec.migration_revision
                    or value.data_revision != request.spec.data_revision):
                raise ProbeFailure("workspace_development_observation_input_mismatch")
        elif type(request) is ResumeWorkspaceDevelopmentEnvironment:
            if (value.data_revision != request.expected_data_revision
                    or value.data_generation != request.expected_data_generation
                    or value.migration_revision != request.spec.migration_revision
                    or value.storage_ref != request.spec.storage_ref):
                raise ProbeFailure("workspace_development_observation_input_mismatch")
        elif type(request) is ResetWorkspaceDevelopmentData:
            if (value.data_generation != request.expected_data_generation + 1
                    or (value.state == "ready" and value.data_revision != request.target_data_revision)):
                raise ProbeFailure("workspace_development_observation_reset_mismatch")
        elif value.data_generation != request.expected_data_generation or value.data_revision != request.expected_data_revision:
            raise ProbeFailure("workspace_development_observation_data_mismatch")
        return value

    def _stop_observation(self, intent, spec, stop_fact: WorkspaceDevelopmentStopFact,
                          state: str, data_generation: int, data_revision: str,
                          source_manifest_digest: str) -> WorkspaceDevelopmentEnvironmentObservation:
        request = intent.request
        if (type(stop_fact) is not WorkspaceDevelopmentStopFact or stop_fact.outcome != "confirmed_stopped"
                or stop_fact.binding != request.binding):
            raise ProbeFailure("workspace_development_stop_unconfirmed")
        runtime_fact = WorkspaceDevelopmentRuntimeFact(
            status="stopped", process_id=None, runner=stop_fact.runner, binding=request.binding,
            source_manifest_digest=source_manifest_digest,
        )
        try:
            return WorkspaceDevelopmentEnvironmentObservation(
                environment_id=request.environment_id, operation_id=request.operation_id,
                request_digest=intent.request_digest, binding=request.binding,
                storage_ref=spec.storage_ref, source_manifest_digest=source_manifest_digest,
                migration_revision=spec.migration_revision, data_revision=data_revision,
                data_generation=data_generation, state=state, runtime_fact=runtime_fact,
                stop_fact=stop_fact,
            )
        except ValueError:
            raise ProbeFailure("workspace_development_stop_observation_invalid") from None

    def _store_observation(self, session, operation, environment,
                           intent, spec, value: WorkspaceDevelopmentEnvironmentObservation,
                           runtime=None) -> str:
        target = _TARGET_STATE[intent.request.action]
        if value.state == target:
            status = "succeeded"
        elif value.state == "failed" and self._physical_state(value) == "stopped":
            status = "failed"
        else:
            status = "unknown"
        operation = dict(operation)
        operation.update({
            "phase": "reconciled" if status in {"succeeded", "failed"} else "may_have_started",
            "operation_state": status, "observation_json": value.model_dump(mode="json"),
            "observation_digest": _observation_digest(value), "failure_code": value.failure_code,
            "updated_at": _now(), "closed_at": _now() if status in {"succeeded", "failed"} else None,
        })
        session.write_operation(operation)
        environment = self._refresh_environment(
            environment, spec, value, intent.request.operation_id, intent.request_digest)
        if runtime is not None and intent.request.action in {"prepare", "resume", "reset_data"}:
            evidence = self._safe_dependency_evidence(runtime)
            if evidence is not None:
                operation["dependency_evidence"] = evidence
                environment["dependency_evidence"] = evidence
        environment["pending_operation_id"] = None if status in {"succeeded", "failed"} else intent.request.operation_id
        if intent.request.action == "reset_data" and status == "succeeded":
            environment["reset_stop_fact_json"] = None
            environment["reset_data_revision"] = None
        session.write_environment(environment)
        session.write_operation(operation)
        return status

    @staticmethod
    def _safe_dependency_evidence(runtime) -> dict | None:
        provider = getattr(runtime, "dependency_evidence", None)
        if not callable(provider):
            return None
        try:
            raw = provider()
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        fields = ("reused", "environment_key", "lock_digest", "dependency_cache_key",
                  "toolchain_digest", "snapshot_digest", "snapshot_bytes")
        evidence = {key: raw[key] for key in fields if key in raw}
        if (type(evidence.get("reused")) is not bool
                or any(not isinstance(evidence.get(key), str) or not re.fullmatch(
                    r"[A-Za-z0-9_.:-]{1,128}", evidence[key])
                       for key in ("environment_key",))
                or any(not isinstance(evidence.get(key), str) or not re.fullmatch(
                    r"sha256:[0-9a-f]{64}", evidence[key])
                       for key in ("lock_digest", "dependency_cache_key", "toolchain_digest", "snapshot_digest"))
                or type(evidence.get("snapshot_bytes")) is not int or evidence["snapshot_bytes"] < 0):
            return None
        return evidence

    def _new_spec_for(self, intent, environment) -> WorkspaceDevelopmentEnvironmentSpec:
        request = intent.request
        if type(request) is PrepareWorkspaceDevelopmentEnvironment:
            return request.spec
        if (type(request) is ResetWorkspaceDevelopmentData
                and request.target_data_revision not in DATASET_REVISIONS):
            raise ProbeFailure("workspace_development_data_revision_unsupported")
        if environment is None:
            raise ProbeFailure("workspace_development_environment_not_found")
        try:
            base = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
        except (KeyError, TypeError, ValueError):
            raise ProbeFailure("workspace_development_journal_spec_invalid") from None
        return _current_spec(base, request)

    def _make_observation_from_runtime(self, runtime, intent, spec, storage, session, environment):
        action, request = intent.request.action, intent.request
        if action == "prepare":
            return runtime.prepare(request, storage, gate=self.gate)
        if runtime.docker is None:
            runtime.discover(storage, prepare_operation_id=runtime.prepare_operation_id)
        runtime.latest_operation_id = request.operation_id
        runtime.latest_request_digest = intent.request_digest
        if action == "resume":
            return runtime.start_existing(request, storage, current_spec=spec, gate=self.gate)
        if action == "reset_data":
            stop_fact = runtime.stop_services(storage, gate=self.gate)
            if type(stop_fact) is not WorkspaceDevelopmentStopFact or stop_fact.outcome != "confirmed_stopped":
                raise ProbeFailure("workspace_development_stop_unconfirmed")
            self._clear_database(runtime, storage, intent, stop_fact, session, environment)
            return runtime.start_existing(request, storage, current_spec=spec, gate=self.gate)
        if action == "suspend":
            stop_fact = runtime.stop_services(storage, gate=self.gate)
            source = observe_workspace_source(storage, request.binding)
            return self._stop_observation(intent, spec, stop_fact, "suspended",
                request.expected_data_generation, request.expected_data_revision, source.manifest_digest)
        if action == "dispose":
            low_level = runtime.stop(request, storage, gate=self.gate)
            if type(low_level) is not WorkspaceDevelopmentEnvironmentObservation or low_level.stop_fact is None:
                raise ProbeFailure("workspace_development_stop_unconfirmed")
            environment["dispose_stop_fact_json"] = low_level.stop_fact.model_dump(mode="json")
            environment["physical_state"] = "stopped"
            environment["updated_at"] = _now()
            session.write_environment(environment)
            environment_path = storage.workspace_root / "runtime-environments" / request.environment_id
            _runtime_mounts_absent(storage, environment_path)
            _remove_environment_data(runtime, storage, request.operation_id, self.gate)
            return self._stop_observation(intent, spec, low_level.stop_fact, "disposed",
                request.expected_data_generation, request.expected_data_revision,
                low_level.source_manifest_digest)
        raise ProbeFailure("workspace_development_action_unsupported")

    def _clear_database(self, runtime, storage, intent, stop_fact, session, environment):
        request = intent.request
        expected = request.expected_environment_revision
        if environment is None or environment.get("environment_revision") != expected + 1:
            raise ProbeFailure("workspace_development_environment_revision_conflict")
        if type(stop_fact) is not WorkspaceDevelopmentStopFact or stop_fact.outcome != "confirmed_stopped":
            raise ProbeFailure("workspace_development_stop_unconfirmed")
        environment["reset_stop_fact_json"] = stop_fact.model_dump(mode="json")
        environment["physical_state"] = "stopped"
        environment["reset_data_revision"] = request.target_data_revision
        environment["updated_at"] = _now()
        session.write_environment(environment)
        _clear_database_directory(runtime, storage, request.operation_id, self.gate)

    def _execute_accepted(self, intent, operation, environment, spec, runtime):
        request = intent.request
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            with journal.environment(request.environment_id) as session:
                current_operation = session.read_operation(request.operation_id)
                current_environment = session.read_environment()
                if current_operation is None:
                    current_operation = self._record_new_intent(
                        session, intent, spec, current_environment)
                    current_environment = session.read_environment()
                else:
                    current_intent = _operation_intent(current_operation, request.operation_id)
                    if current_intent != intent:
                        raise ProbeFailure("workspace_development_operation_identity_conflict")
                    if current_operation.get("operation_state") in {"succeeded", "failed"}:
                        return _observation(current_operation)
                    if current_operation.get("phase") != "accepted":
                        return None
                    if current_environment is None:
                        current_environment = self._record_new_intent(session, intent, spec, None)
                        current_environment = session.read_environment()
                self.gate(request.operation_id)
                current_operation = dict(current_operation)
                current_operation.update({"phase": "may_have_started", "updated_at": _now()})
                session.write_operation(current_operation)
                try:
                    result = self._make_observation_from_runtime(
                        runtime, intent, spec, storage, session, current_environment)
                    value = self._validate_observation(intent, result)
                except Exception as error:
                    current_operation = dict(current_operation)
                    current_operation.update({"operation_state": "unknown", "phase": "may_have_started",
                        "failure_code": _failure_code(error), "updated_at": _now()})
                    current_operation["failure_location"] = [
                        {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                        for frame in traceback.extract_tb(error.__traceback__)[-6:]
                    ]
                    if type(error).__name__ == "_InstallFailure":
                        current_operation["dependency_diagnostic"] = error.detail
                    session.write_operation(current_operation)
                    if current_environment is not None:
                        current_environment = dict(current_environment)
                        current_environment["physical_state"] = "unknown"
                        current_environment["pending_operation_id"] = request.operation_id
                        current_environment["updated_at"] = _now()
                        session.write_environment(current_environment)
                    raise ProbeFailure(_failure_code(error)) from None
                self._store_observation(session, current_operation, current_environment,
                                        intent, spec, value, runtime)
                runtime.observations[request.operation_id] = value
                if value.state in {"suspended", "disposed"}:
                    runtime.close()
                    with self._mutex:
                        self._runtimes.pop(request.environment_id, None)
                elif value.state == "ready":
                    runtime.latest_operation_id = request.operation_id
                    runtime.latest_request_digest = intent.request_digest
                return value

    def apply(self, intent) -> WorkspaceDevelopmentEnvironmentObservation | None:
        checked = _validated_intent(intent)
        request = checked.request
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            existing = journal.operation(request.operation_id)
            if existing is not None:
                previous = _operation_intent(existing, request.operation_id)
                if previous != checked or previous.request_digest != checked.request_digest:
                    raise ProbeFailure("workspace_development_operation_identity_conflict")
                if existing.get("operation_state") in {"succeeded", "failed"}:
                    return _observation(existing)
                if existing.get("phase") != "accepted":
                    return self._reconcile(request.operation_id)
            with journal.environment(request.environment_id) as session:
                environment = session.read_environment()
                if existing is not None and environment is None:
                    raise ProbeFailure("workspace_development_journal_environment_missing")
                if existing is None and environment is None and request.action != "prepare":
                    raise ProbeFailure("workspace_development_environment_not_found")
                spec = self._new_spec_for(checked, environment)
        prepare_operation_id = (request.operation_id if request.action == "prepare" else
                                self._find_prepare_operation(request.environment_id, checked))
        runtime = self._runtime(spec, prepare_operation_id)
        if existing is None:
            self._check_no_open_environment(request.binding.workspace_id, request.environment_id)
        return self._execute_accepted(checked, existing, environment, spec, runtime)

    def _find_prepare_operation(self, environment_id: str, intent) -> str:
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            with journal.environment(environment_id) as session:
                environment = session.read_environment()
                if environment is None:
                    raise ProbeFailure("workspace_development_environment_not_found")
                operation_id, _ = self._prepare_operation(session, environment, intent)
                return operation_id

    def _check_no_open_environment(self, workspace_id: str, requested_environment_id: str) -> None:
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            ids = journal.environment_ids()
            if len(ids) > _MAX_RUNTIME_ENVIRONMENTS:
                raise ProbeFailure("workspace_development_environment_inventory_limit")
            for environment_id in ids:
                if environment_id == requested_environment_id:
                    continue
                environment = journal.read_environment(environment_id)
                if (environment is not None
                        and environment.get("binding", {}).get("workspace_id") == workspace_id
                        and environment.get("state") != "disposed"):
                    raise ProbeFailure("workspace_development_environment_already_open")

    def _reconcile(self, operation_id: str):
        """Recover journaled results by observation; never replay a lifecycle command."""
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            operation = journal.operation(operation_id)
            if operation is None:
                raise ProbeFailure("workspace_development_operation_not_found")
            intent = _operation_intent(operation, operation_id)
            if operation.get("phase") == "accepted":
                raise ProbeFailure("workspace_development_operation_not_found")
            if operation.get("operation_state") in {"succeeded", "failed"}:
                return _observation(operation)
            with journal.environment(intent.request.environment_id) as session:
                environment = session.read_environment()
                if environment is None:
                    raise ProbeFailure("workspace_development_journal_environment_missing")
                spec = self._new_spec_for(intent, environment)
                prepare_operation_id, _ = self._prepare_operation(session, environment, intent)
        runtime = self._runtime(spec, prepare_operation_id)
        with self._storage() as storage:
            runtime.discover(storage, prepare_operation_id=prepare_operation_id)
            observation = runtime.observe_current(
                operation_id, intent.request_digest, spec, storage,
                prepare_operation_id=prepare_operation_id,
            )
        if observation is None:
            with self._storage() as storage:
                with WorkspaceDevelopmentJournal(storage).environment(intent.request.environment_id) as session:
                    record = session.read_operation(operation_id)
                    if record is not None:
                        record.update({"operation_state": "unknown", "failure_code": "workspace_development_observation_unavailable",
                                       "updated_at": _now()})
                        session.write_operation(record)
            return None
        value = self._validate_observation(intent, observation)
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            with journal.environment(intent.request.environment_id) as session:
                current_operation = session.read_operation(operation_id)
                current_environment = session.read_environment()
                if current_operation is None or current_environment is None:
                    raise ProbeFailure("workspace_development_journal_environment_missing")
                self._store_observation(session, current_operation, current_environment,
                                        intent, spec, value, runtime)
        return value

    def query(self, operation_id: str) -> WorkspaceDevelopmentEnvironmentObservation:
        operation = _OPERATION_RE.fullmatch(operation_id) if isinstance(operation_id, str) else None
        if operation is None:
            raise ProbeFailure("workspace_development_operation_not_found")
        value = self._reconcile(operation_id)
        if value is None:
            raise ProbeFailure("workspace_development_observation_unavailable")
        return value

    def registered_readers(self, binding: WorkspaceBinding) -> tuple[RegisteredWorkspaceReader, ...]:
        if type(binding) is not WorkspaceBinding:
            raise ProbeFailure("workspace_development_binding_required")
        result = {}
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            ids = journal.environment_ids()
            if len(ids) > _MAX_RUNTIME_ENVIRONMENTS:
                raise ProbeFailure("workspace_development_environment_inventory_limit")
            environments = [journal.read_environment(item) for item in ids]
        for environment in environments:
            if not environment or environment.get("state") == "disposed":
                continue
            try:
                spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
            except (KeyError, TypeError, ValueError):
                raise ProbeFailure("workspace_development_journal_spec_invalid") from None
            if (spec.binding.workspace_id != binding.workspace_id
                    or spec.binding.project_id != binding.project_id):
                continue
            if spec.binding != binding:
                raise ProbeFailure("workspace_development_binding_stale")
            prepare_operation_id = environment.get("prepare_operation_id")
            if not isinstance(prepare_operation_id, str):
                raise ProbeFailure("workspace_development_prepare_identity_missing")
            with self._storage() as storage:
                from .workspace_development_docker import WorkspaceDevelopmentDocker, METHOD
                from .workspace_development_inputs import workspace_storage_id
                from packages.contracts.p1.workspace_candidates import workspace_runtime_scope_id

                scope = workspace_runtime_scope_id(binding)
                expected = str(storage.workspace_root / workspace_storage_id(binding) / "files")
                readers = []
                for record in WorkspaceDevelopmentDocker.discover_owned(
                        spec.environment_id, scope, operation_id=prepare_operation_id):
                    if record["role"] != "backend":
                        continue
                    source = [mount for mount in record["mounts"] if mount["destination"] == "/workspace"]
                    if (len(source) != 1 or source[0]["type"] != "bind"
                            or source[0]["source"] != expected or not source[0]["readonly"]):
                        raise ProbeFailure("workspace_development_reader_mount_mismatch")
                    readers.append(RegisteredWorkspaceReader(container_id=record["container_id"],
                        operation_id=prepare_operation_id, scope=scope, method=METHOD))
            for reader in readers:
                if (reader.operation_id != prepare_operation_id
                        or reader.scope != workspace_runtime_scope_id(binding)
                        or reader.method != "p1-workspace-development-r1"
                        or reader.mount_destination != "/workspace"):
                    raise ProbeFailure("workspace_development_reader_identity_mismatch")
                if reader.container_id in result and result[reader.container_id] != reader:
                    raise ProbeFailure("workspace_development_reader_identity_conflict")
                result[reader.container_id] = reader
        return tuple(result[key] for key in sorted(result))

    def refresh(self, binding: WorkspaceBinding) -> WorkspaceDevelopmentEnvironmentObservation:
        if type(binding) is not WorkspaceBinding:
            raise ProbeFailure("workspace_development_binding_required")
        with self._storage() as storage:
            manifest = observe_workspace_source(storage, binding)
            journal = WorkspaceDevelopmentJournal(storage)
            environments = [journal.read_environment(item) for item in journal.environment_ids()]
        matches = [value for value in environments if value and
                   value.get("binding", {}).get("workspace_id") == binding.workspace_id
                   and value.get("state") != "disposed"]
        if len(matches) != 1:
            raise ProbeFailure("workspace_development_environment_scope_ambiguous")
        environment = matches[0]
        latest_id = environment.get("latest_operation_id")
        latest_digest = environment.get("latest_request_digest")
        if not isinstance(latest_id, str) or not isinstance(latest_digest, str):
            raise ProbeFailure("workspace_development_operation_not_found")
        try:
            spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
        except (KeyError, TypeError, ValueError):
            raise ProbeFailure("workspace_development_journal_spec_invalid") from None
        current_spec = _current_spec(spec, type("RefreshRequest", (), {
            "binding": binding, "source_manifest_digest": manifest.manifest_digest,
        })())
        prepare_operation_id = environment.get("prepare_operation_id")
        runtime = self._runtime(current_spec, prepare_operation_id)
        with self._storage() as storage:
            runtime.discover(storage, prepare_operation_id=prepare_operation_id)
            refreshed = runtime.refresh(latest_id, latest_digest, current_spec, storage, gate=self.gate)
        if (refreshed.operation_id != latest_id or refreshed.request_digest != latest_digest
                or refreshed.source_manifest_digest != manifest.manifest_digest):
            raise ProbeFailure("workspace_development_refresh_observation_mismatch")
        with self._storage() as storage:
            with WorkspaceDevelopmentJournal(storage).environment(environment["environment_id"]) as session:
                current = session.read_environment()
                current["refresh_manifest_digest"] = manifest.manifest_digest
                current["refresh_observation_json"] = refreshed.model_dump(mode="json")
                current["refresh_observed_at"] = _now()
                current["updated_at"] = _now()
                session.write_environment(current)
        return refreshed

    def close(self) -> None:
        """Stop and verify owned runtimes; unknown state keeps the pool pinned."""
        with self._mutex:
            if self._closed:
                return
        failures = []
        with self._storage() as storage:
            journal = WorkspaceDevelopmentJournal(storage)
            ids = journal.environment_ids()
        if len(ids) > _MAX_RUNTIME_ENVIRONMENTS:
            raise ProbeFailure("workspace_development_cleanup_unconfirmed")
        for environment_id in ids:
            with self._storage() as storage:
                environment = WorkspaceDevelopmentJournal(storage).read_environment(environment_id)
            if not environment or environment.get("physical_state") in {"stopped", "removed"}:
                continue
            try:
                spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
                prepare_operation_id = environment["prepare_operation_id"]
                runtime = self._runtime(spec, prepare_operation_id)
                with self._storage() as storage:
                    runtime.discover(storage, prepare_operation_id=prepare_operation_id)
                    stop_fact = runtime.stop_services(storage, gate=self._shutdown_gate)
                if type(stop_fact) is not WorkspaceDevelopmentStopFact or stop_fact.outcome != "confirmed_stopped":
                    raise ProbeFailure("workspace_development_cleanup_unconfirmed")
                with self._storage() as storage:
                    with WorkspaceDevelopmentJournal(storage).environment(environment_id) as session:
                        current = session.read_environment()
                        current["physical_state"] = "stopped"
                        current["shutdown_stop_fact_json"] = stop_fact.model_dump(mode="json")
                        current["shutdown_observed_at"] = _now()
                        current["pin_state"] = "releasing"
                        current["updated_at"] = _now()
                        session.write_environment(current)
                runtime.close()
                with self._mutex:
                    self._runtimes.pop(environment_id, None)
                with self._storage() as storage:
                    with WorkspaceDevelopmentJournal(storage).environment(environment_id) as session:
                        current = session.read_environment()
                        current["pin_state"] = "released"
                        current["updated_at"] = _now()
                        session.write_environment(current)
            except Exception:
                failures.append(environment_id)
                with self._storage() as storage:
                    with WorkspaceDevelopmentJournal(storage).environment(environment_id) as session:
                        current = session.read_environment()
                        if current is not None:
                            current["physical_state"] = "unknown"
                            current["pin_state"] = "retained_unknown"
                            current["shutdown_failure_code"] = "workspace_development_cleanup_unconfirmed"
                            current["updated_at"] = _now()
                            session.write_environment(current)
        if failures:
            raise ProbeFailure("workspace_development_cleanup_unconfirmed")
        with self._mutex:
            self._closed = True

    def _shutdown_gate(self, operation_id: str) -> None:
        """Permit only stop of a journaled container identity owned by this controller."""
        with self._storage() as storage:
            record = WorkspaceDevelopmentJournal(storage).operation(operation_id)
        if record is None:
            raise ProbeFailure("workspace_development_shutdown_identity_unregistered")

    def dependency_evidence(self, operation_id: str) -> dict:
        """Return the bounded, secret-free dependency receipt captured for an operation."""
        if not isinstance(operation_id, str) or _OPERATION_RE.fullmatch(operation_id) is None:
            raise ProbeFailure("workspace_development_operation_not_found")
        with self._storage() as storage:
            record = WorkspaceDevelopmentJournal(storage).operation(operation_id)
        if record is None:
            raise ProbeFailure("workspace_development_operation_not_found")
        intent = _operation_intent(record, operation_id)
        evidence = record.get("dependency_evidence")
        if not isinstance(evidence, dict) or intent.request.action not in {"prepare", "resume", "reset_data"}:
            raise ProbeFailure("workspace_development_dependency_evidence_unavailable")
        return dict(evidence)

    def _probe_registered(self, storage, binding: WorkspaceBinding, *, kind: str) -> dict:
        if type(binding) is not WorkspaceBinding or kind not in {"devmarker", "notes"}:
            raise ProbeFailure("workspace_development_probe_request_invalid")
        self._check_storage(storage)
        journal = WorkspaceDevelopmentJournal(storage)
        environments = [journal.read_environment(item) for item in journal.environment_ids()]
        matches = []
        for environment in environments:
            if not environment or environment.get("state") == "disposed":
                continue
            try:
                spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
            except (KeyError, TypeError, ValueError):
                raise ProbeFailure("workspace_development_journal_spec_invalid") from None
            if spec.binding.workspace_id != binding.workspace_id:
                continue
            if spec.binding != binding:
                raise ProbeFailure("workspace_development_binding_stale")
            matches.append((environment, spec))
        if len(matches) != 1:
            raise ProbeFailure("workspace_development_environment_scope_ambiguous")
        environment, spec = matches[0]
        prepare_operation_id = environment.get("prepare_operation_id")
        if not isinstance(prepare_operation_id, str):
            raise ProbeFailure("workspace_development_prepare_identity_missing")
        try:
            runtime_type = _runtime_type()
            result = runtime_type.probe_registered_environment(
                spec, prepare_operation_id, storage, binding, kind=kind)
        except ProbeFailure:
            raise
        except Exception:
            raise ProbeFailure("workspace_development_probe_observation_unavailable") from None
        if not isinstance(result, dict):
            raise ProbeFailure("workspace_development_probe_observation_invalid")
        evidence = dict(environment.get("method_probe_evidence") or {})
        evidence[kind] = result
        environment["method_probe_evidence"] = evidence
        environment["updated_at"] = _now()
        with journal.environment(environment["environment_id"]) as session:
            current = session.read_environment()
            if current is None or current.get("binding") != binding.model_dump(mode="json"):
                raise ProbeFailure("workspace_development_binding_stale")
            current["method_probe_evidence"] = evidence
            current["updated_at"] = _now()
            session.write_environment(current)
        return result

    def probe_devmarker(self, storage, binding: WorkspaceBinding) -> dict:
        return self._probe_registered(storage, binding, kind="devmarker")

    def probe_notes(self, storage, binding: WorkspaceBinding) -> dict:
        return self._probe_registered(storage, binding, kind="notes")


_OPERATION_RE = re.compile(r"^workspace-dev-env-(prepare|suspend|resume|reset_data|dispose)-[0-9a-f]{32}$")
