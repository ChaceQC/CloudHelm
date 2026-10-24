"""Bounded mutable Workspace runtime; Hub state and authorization stay external."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import rfc8785

from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at
from modules.workspaces.candidate_writers import process_start_ticks
from packages.contracts.p1.development_environment import (
    DisposeWorkspaceDevelopmentEnvironment, PrepareWorkspaceDevelopmentEnvironment,
    ResetWorkspaceDevelopmentData, ResumeWorkspaceDevelopmentEnvironment,
    WORKSPACE_DEVELOPMENT_PROFILE, WorkspaceDevelopmentEnvironmentObservation,
    WorkspaceDevelopmentProbeFact, WorkspaceDevelopmentRunnerIdentity,
    WorkspaceDevelopmentRuntimeFact, WorkspaceDevelopmentStopFact,
    WorkspaceDevelopmentEnvironmentSpec, workspace_development_operation_digest,
)
from packages.contracts.p1.workspace_candidates import RegisteredWorkspaceReader, workspace_runtime_scope_id
from packages.contracts.p1.workspace_git import WorkspaceBinding, content_digest

from .artifact_environment_docker import EnvironmentGroup, METHOD as ARTIFACT_METHOD, command
from .development_storage import DevelopmentStorage
from .engineering_registry import EngineeringStorage
from . import python_dependencies
from .python_dependencies import PythonDependencyInput
from .toolchain import DockerClient, ProbeFailure, private_directory
from .workspace_development_dependencies import (
    WorkspaceDependencyReceipt, _cached_receipt, prepare_workspace_dependencies,
)
from .workspace_development_docker import (
    WorkspaceDevelopmentDocker, inspect_fixed_image,
)
from .workspace_development_recipe import (
    DATABASE_NAME, DATABASE_OWNER, DATASET_REVISIONS, MIGRATION_HEAD_QUERY,
    MIGRATION_REVISION as FIXED_MIGRATION_REVISION, POSTGRES_IMAGE_DIGEST,
    POSTGRES_REFERENCE, PYTHON_IMAGE_DIGEST, PYTHON_REFERENCE, data_statements,
    seed_count_statement,
)
from .workspace_development_inputs import (
    WORKSPACE_PYTHON_TOOLCHAIN, read_workspace_backend_inputs, validate_workspace_dependency_inputs,
    workspace_storage_id,
)
from .workspace_development_probe import probe_workspace_backend, workspace_server_process_id
from .workspace_development_source import WorkspaceSourceObservation, observe_workspace_source

RUNTIME_DIRECTORY = "runtime-environments"
MAX_DATABASE_PASSWORD_BYTES = 256
_ACTIVE_RUNTIMES: dict[str, "WorkspaceDevelopmentRuntime"] = {}


def _invoke_gate(gate, operation_id: str) -> None:
    if gate is not None:
        gate(operation_id)


def _safe_id(value: str, pattern: str, category: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ProbeFailure(category)


def _private_child(parent_fd: int, name: str, device: int, *, create: bool) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", name) or name in {".", ".."}:
        raise ProbeFailure("workspace_development_directory_name_invalid")
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            raise ProbeFailure("workspace_development_runtime_already_exists") from None
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=parent_fd)
        state = os.fstat(descriptor)
        if (state.st_dev != device or state.st_uid != os.geteuid() or state.st_mode & 0o077):
            os.close(descriptor)
            raise ProbeFailure("workspace_development_private_directory_mismatch")
        if create:
            os.fchmod(descriptor, 0o700)
        return descriptor
    except ProbeFailure:
        raise
    except OSError:
        raise ProbeFailure("workspace_development_private_directory_unavailable") from None


def _write_private_file(parent_fd: int, name: str, data: bytes) -> None:
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_DATABASE_PASSWORD_BYTES:
        raise ProbeFailure("workspace_development_private_file_value_invalid")
    descriptor = -1
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o400, dir_fd=parent_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ProbeFailure("workspace_development_private_file_boundary_mismatch")
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ProbeFailure("workspace_development_private_file_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.fsync(parent_fd)
    except ProbeFailure:
        raise
    except OSError:
        raise ProbeFailure("workspace_development_private_file_write_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_private_file(parent_fd: int, name: str, *, limit: int = MAX_DATABASE_PASSWORD_BYTES) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=parent_fd)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_mode & 0o077
                or before.st_nlink != 1 or before.st_size > limit):
            raise ProbeFailure("workspace_development_private_file_boundary_mismatch")
        raw = os.read(descriptor, limit + 1)
        after = os.fstat(descriptor)
        if (len(raw) != before.st_size or before.st_ino != after.st_ino or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            raise ProbeFailure("workspace_development_private_file_changed")
        return raw
    except ProbeFailure:
        raise
    except OSError:
        raise ProbeFailure("workspace_development_private_file_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class WorkspaceDevelopmentRuntime:
    """Physical Runner facts for one fixed profile and one mutable Workspace."""

    def __init__(self, spec: WorkspaceDevelopmentEnvironmentSpec, *, runner_id: str | None = None):
        if type(spec) is not WorkspaceDevelopmentEnvironmentSpec:
            raise ProbeFailure("workspace_development_spec_required")
        self.spec = spec
        self.binding = spec.binding
        self.runner_id = runner_id or "controlled-dev-runner-" + spec.storage_ref.storage_id[-16:]
        self.runner_generation = 0
        self.pin_context = None
        self.pin = None
        self.pinned_storage: EngineeringStorage | None = None
        self.group = EnvironmentGroup(spec.storage_ref.storage_id)
        self.client: DockerClient | None = None
        self.docker: WorkspaceDevelopmentDocker | None = None
        self.dependency_receipt: WorkspaceDependencyReceipt | None = None
        self.prepare_operation_id: str | None = None
        self.latest_operation_id: str | None = None
        self.latest_request_digest: str | None = None
        self.runtime_directory: Path | None = None
        self.database_directory: Path | None = None
        self.secrets_directory: Path | None = None
        self.application_password_path: Path | None = None
        self._runtime_fd = -1
        self._database_fd = -1
        self._secrets_fd = -1
        self._workspace_root: PrivateRoot | None = None
        self._workspace_files_fd = -1
        self.workspace_source: str | None = None
        self.owner_password: str | None = None
        self.app_password: str | None = None
        self.state = "preparing"
        self.data_generation = spec.data_generation
        self.last_source_digest: str | None = None
        self.last_process_id: str | None = None
        self.observations: dict[str, WorkspaceDevelopmentEnvironmentObservation] = {}

    def acquire_storage_pin(self) -> None:
        """Acquire the long-lived backing pin before opening a short storage admission."""
        if self.pin is not None:
            self.pin.observe()
            return
        try:
            self.pin_context = DevelopmentStorage(self.spec.storage_ref.storage_id).pin_ref(
                self.spec.storage_ref, requested_bytes=0)
            self.pin = self.pin_context.__enter__()
            data_root = self.pin.directory.parent
            self.pinned_storage = EngineeringStorage(
                admission=self.pin, git_root=data_root / "git", workspace_root=data_root / "workspace",
                cache_root=data_root / "cache", archive_root=data_root / "archive")
            self.pin.observe()
            self.runner_generation = process_start_ticks(os.getpid())
        except Exception as error:
            if self.pin_context is not None:
                try:
                    self.pin_context.__exit__(type(error), error, error.__traceback__)
                except Exception:
                    pass
            self.pin_context = self.pin = None
            raise ProbeFailure("workspace_development_storage_pin_unavailable") from None

    def _hold_pin(self, storage: EngineeringStorage) -> None:
        if self.pin is not None:
            self.pin.observe()
            return
        try:
            owner = DevelopmentStorage(self.spec.storage_ref.storage_id)
            pin_admission = getattr(owner, "pin_admission", None)
            if callable(pin_admission):
                self.pin_context = pin_admission(storage.admission)
            else:
                self.pin_context = owner.pin_ref(self.spec.storage_ref, requested_bytes=0)
            self.pin = self.pin_context.__enter__()
            data_root = self.pin.directory.parent
            self.pinned_storage = EngineeringStorage(
                admission=self.pin, git_root=data_root / "git", workspace_root=data_root / "workspace",
                cache_root=data_root / "cache", archive_root=data_root / "archive")
            self.runner_generation = process_start_ticks(os.getpid())
        except Exception:
            if self.pin_context is not None:
                try:
                    self.pin_context.__exit__(None, None, None)
                except Exception:
                    pass
            self.pin_context = self.pin = None
            raise ProbeFailure("workspace_development_storage_pin_unavailable") from None

    def _validate_storage(self, storage: EngineeringStorage) -> None:
        try:
            storage.observe()
            snapshot = storage.admission.snapshot
            registration = snapshot.registration
            if (registration.storage_id != self.spec.storage_ref.storage_id
                    or registration.instance_revision != self.spec.storage_ref.instance_revision
                    or snapshot.purpose != "workspace"
                    or storage.workspace_root != self.pinned_storage.workspace_root
                    or storage.cache_root != self.pinned_storage.cache_root):
                raise ProbeFailure("workspace_development_storage_reference_mismatch")
            if self.pin is not None:
                self.pin.observe()
        except ProbeFailure:
            raise
        except Exception:
            raise ProbeFailure("workspace_development_storage_admission_required") from None

    def _validate_spec(self, spec: WorkspaceDevelopmentEnvironmentSpec) -> None:
        if (type(spec) is not WorkspaceDevelopmentEnvironmentSpec
                or spec.environment_id != self.spec.environment_id
                or spec.storage_ref != self.spec.storage_ref
                or spec.profile_revision != WORKSPACE_DEVELOPMENT_PROFILE
                or spec.toolchain.artifact_digest != WORKSPACE_PYTHON_TOOLCHAIN.digest
                or spec.source_mount != "workspace_read_only_dynamic"
                or spec.file_mutation_authority != "controlled_workspace_service"
                or spec.migration_revision != FIXED_MIGRATION_REVISION
                or spec.data_revision not in DATASET_REVISIONS):
            raise ProbeFailure("workspace_development_spec_outside_fixed_profile")

    def _open_runtime_directories(self, storage: EngineeringStorage, *, create: bool) -> None:
        if self._runtime_fd >= 0:
            return
        root = PrivateRoot(storage.workspace_root)
        envs_fd = runtime_fd = database_fd = secrets_fd = -1
        try:
            with root.exclusive() as root_fd:
                try:
                    envs_fd = os.open(RUNTIME_DIRECTORY,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(RUNTIME_DIRECTORY, 0o700, dir_fd=root_fd)
                    envs_fd = os.open(RUNTIME_DIRECTORY,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
                envs_info = os.fstat(envs_fd)
                if (envs_info.st_dev != os.fstat(root_fd).st_dev or envs_info.st_uid != os.geteuid()
                        or envs_info.st_mode & 0o077):
                    raise ProbeFailure("workspace_development_runtime_root_invalid")
                if create:
                    os.fchmod(envs_fd, 0o700)
                runtime_fd = _private_child(envs_fd, self.spec.environment_id, envs_info.st_dev, create=create)
                runtime_path = Path(os.readlink(f"/proc/self/fd/{runtime_fd}"))
                database_fd = _private_child(runtime_fd, "database", envs_info.st_dev, create=create)
                secrets_fd = _private_child(runtime_fd, ".secrets", envs_info.st_dev, create=create)
                database_path = Path(os.readlink(f"/proc/self/fd/{database_fd}"))
                secrets_path = Path(os.readlink(f"/proc/self/fd/{secrets_fd}"))
                expected = Path(storage.workspace_root) / RUNTIME_DIRECTORY / self.spec.environment_id
                if runtime_path != expected or database_path != expected / "database" or secrets_path != expected / ".secrets":
                    raise ProbeFailure("workspace_development_runtime_path_mismatch")
                self._runtime_fd, self._database_fd, self._secrets_fd = runtime_fd, database_fd, secrets_fd
                runtime_fd = database_fd = secrets_fd = -1
                self.runtime_directory, self.database_directory, self.secrets_directory = (
                    runtime_path, database_path, secrets_path)
                self.application_password_path = runtime_path / "application-password"
            self._load_or_create_credentials(create=create)
        except ProbeFailure:
            raise
        except (OSError, ValueError, WorkspaceFileError):
            raise ProbeFailure("workspace_development_runtime_directory_unavailable") from None
        finally:
            root.close()
            for descriptor in (envs_fd, runtime_fd, database_fd, secrets_fd):
                if descriptor >= 0:
                    os.close(descriptor)

    def _load_or_create_credentials(self, *, create: bool) -> None:
        if self._runtime_fd < 0 or self._secrets_fd < 0:
            raise ProbeFailure("workspace_development_runtime_directory_required")
        if create:
            self.owner_password = secrets.token_hex(32)
            self.app_password = secrets.token_hex(32)
            _write_private_file(self._secrets_fd, "owner", self.owner_password.encode("ascii"))
            _write_private_file(self._secrets_fd, "owner.pgpass",
                (f"localhost:5432:{DATABASE_NAME}:{DATABASE_OWNER}:" + self.owner_password + "\n").encode("ascii"))
            _write_private_file(self._runtime_fd, "application-password", self.app_password.encode("ascii"))
        else:
            owner = _read_private_file(self._secrets_fd, "owner").decode("ascii")
            app = _read_private_file(self._runtime_fd, "application-password").decode("ascii")
            pgpass = _read_private_file(self._secrets_fd, "owner.pgpass").decode("ascii")
            if (not re.fullmatch(r"[0-9a-f]{64}", owner) or not re.fullmatch(r"[0-9a-f]{64}", app)
                    or pgpass != f"localhost:5432:{DATABASE_NAME}:{DATABASE_OWNER}:" + owner + "\n"):
                raise ProbeFailure("workspace_development_private_credentials_invalid")
            self.owner_password, self.app_password = owner, app

    def _open_workspace_files(self, storage: EngineeringStorage, binding: WorkspaceBinding) -> WorkspaceSourceObservation:
        self._validate_storage(storage)
        observed = observe_workspace_source(storage, binding)
        if self._workspace_files_fd >= 0:
            if observed.source_path != self.workspace_source:
                raise ProbeFailure("workspace_development_source_path_changed")
            return observed
        root = PrivateRoot(storage.workspace_root)
        files_fd = -1
        try:
            with root.exclusive() as root_fd:
                workspace_id = workspace_storage_id(binding)
                with directory_at(root_fd, workspace_id) as workspace_fd, directory_at(workspace_fd, "files") as source_fd:
                    files_fd = os.dup(source_fd)
                    source = os.readlink(f"/proc/self/fd/{files_fd}")
            if source != observed.source_path:
                raise ProbeFailure("workspace_development_source_path_mismatch")
            self._workspace_root, self._workspace_files_fd, self.workspace_source = root, files_fd, source
            return observed
        except ProbeFailure:
            if files_fd >= 0:
                os.close(files_fd)
            root.close()
            raise
        except (OSError, ValueError, WorkspaceFileError):
            if files_fd >= 0:
                os.close(files_fd)
            root.close()
            raise ProbeFailure("workspace_development_source_view_unavailable") from None

    def _make_client(self, *, create: bool = True) -> DockerClient:
        if self.runtime_directory is None:
            raise ProbeFailure("workspace_development_runtime_directory_required")
        root = self.runtime_directory / "docker-client"
        if create:
            private_directory(root)
        else:
            try:
                root_state = root.lstat()
                if (not stat.S_ISDIR(root_state.st_mode) or root_state.st_uid != os.geteuid()
                        or root_state.st_mode & 0o077):
                    raise ProbeFailure("workspace_development_docker_config_unavailable")
            except OSError:
                raise ProbeFailure("workspace_development_docker_config_unavailable") from None
        config = root / "docker-public"
        try:
            if not config.exists():
                if not create:
                    raise ProbeFailure("workspace_development_docker_config_unavailable")
                os.mkdir(config, 0o700)
            state = config.lstat()
            if (not stat.S_ISDIR(state.st_mode) or state.st_uid != os.geteuid() or state.st_mode & 0o077
                    or os.listdir(config)):
                raise ProbeFailure("workspace_development_docker_config_not_empty")
        except ProbeFailure:
            raise
        except OSError:
            raise ProbeFailure("workspace_development_docker_config_unavailable") from None
        self.client = DockerClient(config)
        return self.client

    def _acquire_group(self, *, fresh: bool) -> None:
        if self.group.lock is not None:
            self.group.observe()
            return
        if fresh:
            self.group.create()
            return
        self.group.acquire()
        path = Path("/sys/fs/cgroup") / self.group.unit
        if not path.is_dir():
            raise ProbeFailure("workspace_development_parent_group_unavailable")
        result = command(["/usr/bin/systemctl", "show", self.group.unit,
            "--property=Description,Transient"])
        values = dict(line.split("=", 1) for line in result.stdout.decode("utf-8").splitlines() if "=" in line)
        if values != {"Description": ARTIFACT_METHOD, "Transient": "yes"}:
            raise ProbeFailure("workspace_development_parent_group_identity_mismatch")
        self.group.path, self.group.created, self.group.external = path, True, True
        self.group.observe()

    def _observe_existing_group(self) -> None:
        """Read limits for readers/controllers without taking the execution mutex."""
        path = Path("/sys/fs/cgroup") / self.group.unit
        if not path.is_dir():
            raise ProbeFailure("workspace_development_parent_group_unavailable")
        result = command(["/usr/bin/systemctl", "show", self.group.unit,
            "--property=Description,Transient"])
        values = dict(line.split("=", 1) for line in result.stdout.decode("utf-8").splitlines() if "=" in line)
        if values != {"Description": ARTIFACT_METHOD, "Transient": "yes"}:
            raise ProbeFailure("workspace_development_parent_group_identity_mismatch")
        self.group.path, self.group.created, self.group.external = path, True, True
        self.group.observe()

    def _make_docker(self, receipt: WorkspaceDependencyReceipt | None = None) -> WorkspaceDevelopmentDocker:
        if (self.client is None or self.runtime_directory is None or self.database_directory is None
                or self.secrets_directory is None or self.workspace_source is None
                or self.prepare_operation_id is None or self.owner_password is None or self.app_password is None
                or self.group.path is None):
            raise ProbeFailure("workspace_development_docker_composition_incomplete")
        source = None if receipt is None else receipt.snapshot_path
        snapshot_digest = None if receipt is None else receipt.snapshot_digest
        snapshot_bytes = None if receipt is None else receipt.snapshot_bytes
        if self.docker is None:
            self.docker = WorkspaceDevelopmentDocker(
                client=self.client, environment_id=self.spec.environment_id,
                scope_id=workspace_runtime_scope_id(self.binding), operation_id=self.prepare_operation_id,
                cgroup_parent=self.group.unit, cgroup_path=self.group.path,
                database_directory=self.database_directory, secrets_directory=self.secrets_directory,
                workspace_source=self.workspace_source, snapshot_source=source,
                snapshot_digest=snapshot_digest, snapshot_bytes=snapshot_bytes,
                app_password=self.app_password, owner_password=self.owner_password,
                data_revision=self.spec.data_revision)
        else:
            self.docker.snapshot_source, self.docker.snapshot_digest, self.docker.snapshot_bytes = (
                source, snapshot_digest, snapshot_bytes)
            self.docker.data_revision = self.spec.data_revision
            self.docker.scope_id = workspace_runtime_scope_id(self.binding)
        return self.docker

    def _verify_receipt(self, receipt: WorkspaceDependencyReceipt, spec: WorkspaceDevelopmentEnvironmentSpec,
                        storage: EngineeringStorage) -> None:
        self._validate_spec(spec)
        if (receipt.binding != spec.binding or not receipt.verified
                or receipt.toolchain_digest != spec.toolchain.artifact_digest
                or "sha256:" + receipt.environment_key != spec.dependency_cache_key
                or receipt.lock_digest != spec.original_lock_digest
                or receipt.python != WORKSPACE_PYTHON_TOOLCHAIN.python
                or receipt.uv != WORKSPACE_PYTHON_TOOLCHAIN.uv
                or receipt.platform != WORKSPACE_PYTHON_TOOLCHAIN.platform):
            raise ProbeFailure("workspace_development_dependency_receipt_mismatch")
        cache_root = PrivateRoot(storage.cache_root)
        descriptor = -1
        try:
            archive = Path(receipt.snapshot_path)
            if (archive.name != "dependencies.tar.gz" or archive.parent != Path(receipt.dependency_directory)
                    or not archive.is_absolute()):
                raise ProbeFailure("workspace_development_dependency_archive_identity_invalid")
            relative = archive.relative_to(Path(storage.cache_root))
            if ".." in relative.parts or relative.is_absolute():
                raise ProbeFailure("workspace_development_dependency_archive_path_invalid")
            parent_path = relative.parent.as_posix()
            with directory_at(cache_root.fd, parent_path) as parent:
                descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                     dir_fd=parent)
                before = os.fstat(descriptor)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                        or before.st_mode & 0o222 or before.st_nlink != 1
                        or before.st_size != receipt.snapshot_bytes or not 0 < before.st_size <= 192 * 1024**2):
                    raise ProbeFailure("workspace_development_dependency_archive_boundary_mismatch")
                digest = hashlib.sha256()
                while block := os.read(descriptor, 1024**2):
                    digest.update(block)
                after = os.fstat(descriptor)
                if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ProbeFailure("workspace_development_dependency_archive_changed")
                if "sha256:" + digest.hexdigest() != receipt.snapshot_digest:
                    raise ProbeFailure("workspace_development_dependency_archive_digest_mismatch")
        except ProbeFailure:
            raise
        except (OSError, ValueError, WorkspaceFileError):
            raise ProbeFailure("workspace_development_dependency_archive_unavailable") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            cache_root.close()

    def _prepare_dependencies(self, storage: EngineeringStorage, spec: WorkspaceDevelopmentEnvironmentSpec,
                              operation_id: str, gate=None) -> WorkspaceDependencyReceipt:
        if self.client is None or self.group.lock is None:
            raise ProbeFailure("workspace_development_dependency_prerequisite_missing")
        _invoke_gate(gate, operation_id)
        receipt = prepare_workspace_dependencies(
            spec.binding, storage, docker_client=self.client, cgroup_parent=self.group.unit,
            dependency_input=PythonDependencyInput(),
            toolchain=WORKSPACE_PYTHON_TOOLCHAIN)
        self._verify_receipt(receipt, spec, storage)
        self.dependency_receipt = receipt
        return receipt

    def dependency_evidence(self) -> dict:
        receipt = self.dependency_receipt
        if receipt is None:
            raise ProbeFailure("workspace_development_dependency_evidence_unavailable")
        return {
            "reused": receipt.reused, "environment_key": receipt.environment_key,
            "lock_digest": receipt.lock_digest, "project_digest": receipt.project_digest,
            "toolchain_digest": receipt.toolchain_digest,
            "dependency_cache_key": receipt.dependency_cache_key,
            "seed_manifest_digest": receipt.seed_manifest_digest,
            "snapshot_digest": receipt.snapshot_digest, "snapshot_bytes": receipt.snapshot_bytes,
            "distributions": dict(receipt.distributions),
            "archive_member_count": receipt.archive_member_count,
            "archive_expanded_bytes": receipt.archive_expanded_bytes,
        }

    def _runner(self, operation_id: str, binding: WorkspaceBinding, source_digest: str,
                evidence: dict) -> WorkspaceDevelopmentRunnerIdentity:
        observation_id = uuid4().hex
        digest = content_digest(rfc8785.dumps({"observation_id": observation_id,
            "operation_id": operation_id, "environment_id": self.spec.environment_id,
            "runner_id": self.runner_id, "runner_generation": self.runner_generation,
            "binding": binding.model_dump(mode="json"), "source_manifest_digest": source_digest,
            "evidence": evidence}))
        return WorkspaceDevelopmentRunnerIdentity(
            runner_id=self.runner_id, runner_generation=self.runner_generation,
            observation_id=observation_id, observation_digest=digest, observed_at=datetime.now(UTC))

    def _ready_observation(self, operation_id: str, request_digest: str, spec: WorkspaceDevelopmentEnvironmentSpec,
                           source: WorkspaceSourceObservation, report: dict, process_id: str,
                           migration_head: str, data_generation: int) -> WorkspaceDevelopmentEnvironmentObservation:
        evidence = {"source_manifest_digest": source.manifest_digest, "process_id": process_id,
            "migration_revision": migration_head, "health_digest": report["health_digest"],
            "ready_digest": report["ready_digest"], "notes_digest": report["notes_digest"],
            "devmarker_status": report["devmarker_status"],
            "devmarker_digest": report["devmarker_digest"], "notes": report["notes"]}
        runner = self._runner(operation_id, spec.binding, source.manifest_digest, evidence)
        runtime = WorkspaceDevelopmentRuntimeFact(
            status="running", process_id=process_id, runner=runner, binding=spec.binding,
            source_manifest_digest=source.manifest_digest)
        health = WorkspaceDevelopmentProbeFact(path="/health", outcome="passed",
            response_digest=report["health_digest"], process_id=process_id, runner=runner,
            binding=spec.binding, source_manifest_digest=source.manifest_digest)
        ready = WorkspaceDevelopmentProbeFact(path="/ready", outcome="passed",
            response_digest=report["ready_digest"], process_id=process_id, runner=runner,
            binding=spec.binding, source_manifest_digest=source.manifest_digest,
            observed_migration_revision=migration_head)
        result = WorkspaceDevelopmentEnvironmentObservation(
            environment_id=spec.environment_id, operation_id=operation_id, request_digest=request_digest,
            binding=spec.binding, storage_ref=spec.storage_ref,
            source_manifest_digest=source.manifest_digest, migration_revision=spec.migration_revision,
            data_revision=spec.data_revision, data_generation=data_generation, state="ready",
            runtime_fact=runtime, health_probe=health, ready_probe=ready)
        self.latest_operation_id, self.latest_request_digest = operation_id, request_digest
        self.binding, self.spec, self.data_generation = spec.binding, spec, data_generation
        self.last_source_digest, self.last_process_id, self.state = source.manifest_digest, process_id, "ready"
        self.observations[operation_id] = result
        _ACTIVE_RUNTIMES[self.spec.environment_id] = self
        return result

    def _wait_ready(self, storage: EngineeringStorage, spec: WorkspaceDevelopmentEnvironmentSpec,
                    expected_source_digest: str, *, previous_process_id: str | None = None,
                    require_reload: bool = False) -> tuple[WorkspaceSourceObservation, dict, str, str]:
        if self.docker is None or self.client is None or self.group.path is None:
            raise ProbeFailure("workspace_development_runtime_not_started")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            storage.observe()
            if self.pin is not None:
                self.pin.observe()
            before = observe_workspace_source(storage, spec.binding)
            if before.source_path != self.workspace_source or before.manifest_digest != expected_source_digest:
                raise ProbeFailure("workspace_development_source_spec_stale")
            try:
                database = self._migration_head()
                if database != spec.migration_revision:
                    raise ProbeFailure("workspace_development_database_migration_head_mismatch")
                self.docker.verify_container("postgres")
                self.docker.verify_container("backend")
                process_id = workspace_server_process_id(
                    self.client, self.docker.containers["backend"], self.group.path)
                report = probe_workspace_backend(self.client, self.docker.containers["backend"])
                after = observe_workspace_source(storage, spec.binding)
                if (after.source_path != before.source_path or after.manifest_digest != before.manifest_digest
                        or report["seed_verified"] is not True):
                    raise ProbeFailure("workspace_development_probe_source_unstable")
                if require_reload and previous_process_id == process_id:
                    time.sleep(0.5)
                    continue
                return after, report, process_id, database
            except ProbeFailure as failure:
                if failure.category not in {
                    "workspace_development_http_probe_not_ready",
                    "workspace_development_server_process_identity_unconfirmed",
                }:
                    raise
            time.sleep(0.5)
        raise ProbeFailure("workspace_development_application_readiness_timeout")

    def _migration_head(self) -> str:
        if self.docker is None:
            raise ProbeFailure("workspace_development_database_not_connected")
        result = self.docker.sql(MIGRATION_HEAD_QUERY, required=False)
        if result.returncode != 0:
            raise ProbeFailure("workspace_development_migration_head_unavailable")
        try:
            return result.stdout.decode("utf-8").strip()
        except UnicodeError:
            raise ProbeFailure("workspace_development_migration_head_invalid") from None

    def _wait_database(self, storage: EngineeringStorage, operation_id: str, gate=None) -> None:
        if self.docker is None:
            raise ProbeFailure("workspace_development_database_not_connected")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            storage.observe()
            if self.pin is not None:
                self.pin.observe()
            self.docker.verify_container("postgres")
            result = self.docker.sql("SELECT 1;", required=False)
            if result.returncode == 0 and result.stdout.strip() == b"1":
                return
            time.sleep(0.5)
        raise ProbeFailure("workspace_development_database_readiness_timeout")

    def _run_migration(self, storage: EngineeringStorage, spec: WorkspaceDevelopmentEnvironmentSpec,
                       operation_id: str, gate=None) -> None:
        if self.docker is None:
            raise ProbeFailure("workspace_development_migration_docker_unavailable")
        if "migration" in self.docker.containers:
            observed = self.docker.inspect("migration")
            if observed["State"].get("Running") is True:
                raise ProbeFailure("workspace_development_previous_migration_unsettled")
            self.docker.remove_exited("migration")
        _invoke_gate(gate, operation_id)
        self.docker.create_migration(spec.migration_revision)
        _invoke_gate(gate, operation_id)
        self.docker.start("migration")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            storage.observe()
            if self.pin is not None:
                self.pin.observe()
            code = self.docker.migration_exit()
            if code is not None:
                if code != 0:
                    raise ProbeFailure("workspace_development_migration_failed")
                _invoke_gate(gate, operation_id)
                self.docker.remove_exited("migration")
                if self._migration_head() != spec.migration_revision:
                    raise ProbeFailure("workspace_development_migration_head_mismatch")
                return
            time.sleep(0.5)
        raise ProbeFailure("workspace_development_migration_timeout")

    def _prepare_data(self, spec: WorkspaceDevelopmentEnvironmentSpec, operation_id: str, gate=None) -> None:
        if self.docker is None or self.app_password is None:
            raise ProbeFailure("workspace_development_data_prerequisite_missing")
        initialize, seed_query, other_query, security_query = data_statements(spec.data_revision)
        _invoke_gate(gate, operation_id)
        result = self.docker.sql(initialize.format(password=self.app_password), required=False)
        if result.returncode:
            raise ProbeFailure("workspace_development_synthetic_data_initialization_failed")
        head = self._migration_head()
        seed = self.docker.sql(seed_query, required=False)
        other_title = self.docker.sql(other_query, required=False)
        security = self.docker.sql(security_query, required=False)
        if (head != spec.migration_revision or seed.returncode or seed.stdout.strip() != b"1"
                or other_title.returncode or other_title.stdout.strip() != b"0"
                or security.returncode or security.stdout.strip() not in (b"t", b"true")):
            raise ProbeFailure("workspace_development_data_or_authorization_mismatch")

    def discover(self, storage: EngineeringStorage, *, prepare_operation_id: str) -> WorkspaceDevelopmentRuntime:
        """Read exact saved Docker identities; it never starts or repairs resources."""
        _safe_id(prepare_operation_id,
            r"workspace-dev-env-prepare-[0-9a-f]{32}", "workspace_development_prepare_operation_invalid")
        self._validate_spec(self.spec)
        self._hold_pin(storage)
        self._validate_storage(storage)
        self.prepare_operation_id = prepare_operation_id
        self._latest_operation_id = self.latest_operation_id or prepare_operation_id
        self._open_runtime_directories(storage, create=False)
        self._open_workspace_files(storage, self.binding)
        if self.client is None:
            self._make_client(create=False)
        self._observe_existing_group()
        scope_id = workspace_runtime_scope_id(self.binding)
        records = WorkspaceDevelopmentDocker.discover_owned(
            self.spec.environment_id, scope_id, operation_id=prepare_operation_id)
        if len({item["role"] for item in records}) != len(records):
            raise ProbeFailure("workspace_development_container_duplicate_role")
        network = WorkspaceDevelopmentDocker.discover_network(
            self.spec.environment_id, scope_id, prepare_operation_id)
        if records and network is None:
            raise ProbeFailure("workspace_development_network_missing_for_containers")
        source_mounts = [mount for item in records for mount in item["mounts"]
                         if item["role"] == "backend" and mount["destination"] == "/workspace"]
        if source_mounts and (len(source_mounts) != 1 or source_mounts[0]["source"] != self.workspace_source
                              or source_mounts[0]["readonly"] is not True):
            raise ProbeFailure("workspace_development_reader_mount_mismatch")
        snapshot_mounts = [mount for item in records for mount in item["mounts"]
                           if item["role"] == "backend"
                           and mount["destination"] == "/workspace-cache/dependencies.tar.gz"]
        snapshot_source = None
        if snapshot_mounts:
            if len(snapshot_mounts) != 1 or snapshot_mounts[0]["readonly"] is not True:
                raise ProbeFailure("workspace_development_snapshot_mount_mismatch")
            candidate = Path(snapshot_mounts[0]["source"])
            try:
                candidate.relative_to(Path(storage.cache_root))
            except ValueError:
                raise ProbeFailure("workspace_development_snapshot_path_outside_cache") from None
            if not candidate.is_absolute() or candidate.name != "dependencies.tar.gz":
                raise ProbeFailure("workspace_development_snapshot_path_invalid")
            snapshot_source = candidate
        self.docker = WorkspaceDevelopmentDocker(
            client=self.client, environment_id=self.spec.environment_id, scope_id=scope_id,
            operation_id=prepare_operation_id, cgroup_parent=self.group.unit,
            cgroup_path=self.group.path, database_directory=self.database_directory,
            secrets_directory=self.secrets_directory, workspace_source=self.workspace_source,
            snapshot_source=snapshot_source, snapshot_digest=None, snapshot_bytes=None,
            app_password=self.app_password, owner_password=self.owner_password,
            data_revision=self.spec.data_revision)
        self.docker.containers = {item["role"]: item["container_id"] for item in records}
        self.docker.network_id = None if network is None else network["network_id"]
        self.last_source_digest = observe_workspace_source(storage, self.binding).manifest_digest
        return self

    def _current_spec_for_existing(self, request, current_spec):
        if type(request) is ResumeWorkspaceDevelopmentEnvironment:
            spec = request.spec
            if (request.environment_id != self.spec.environment_id or request.binding != spec.binding
                    or request.source_manifest_digest != spec.source_manifest_digest
                    or request.expected_data_revision != spec.data_revision
                    or request.expected_data_generation != spec.data_generation):
                raise ProbeFailure("workspace_development_resume_request_mismatch")
            return spec, spec.data_generation
        if type(request) is ResetWorkspaceDevelopmentData:
            if type(current_spec) is not WorkspaceDevelopmentEnvironmentSpec:
                raise ProbeFailure("workspace_development_reset_current_spec_required")
            if (current_spec.environment_id != self.spec.environment_id
                    or current_spec.binding != request.binding
                    or current_spec.source_manifest_digest != request.source_manifest_digest
                    or current_spec.data_revision != request.target_data_revision
                    or current_spec.data_generation != request.expected_data_generation + 1
                    or request.target_data_revision not in DATASET_REVISIONS):
                raise ProbeFailure("workspace_development_reset_request_mismatch")
            return current_spec, current_spec.data_generation
        raise ProbeFailure("workspace_development_start_existing_request_invalid")

    def _validate_discovered_network(self) -> None:
        if self.docker is None or self.docker.network_id is None:
            raise ProbeFailure("workspace_development_network_not_discovered")
        network = self.docker.network_id
        try:
            from .artifact_environment_docker import engine

            actual = engine("GET", "/networks/" + network)
        except ProbeFailure:
            raise
        labels = actual.get("Labels") or {}
        if (actual.get("Id") != network or actual.get("Internal") is not True
                or actual.get("Driver") != "bridge"
                or labels.get("cloudhelm.method") != self.docker._labels().get("cloudhelm.method")
                or labels.get("cloudhelm.operation_id") != self.prepare_operation_id
                or labels.get("cloudhelm.environment_id") != self.spec.environment_id
                or labels.get("cloudhelm.scope") != workspace_runtime_scope_id(self.binding)):
            raise ProbeFailure("workspace_development_network_identity_mismatch")

    def _replace_stale_backend(self, receipt: WorkspaceDependencyReceipt, operation_id: str, gate=None) -> None:
        if self.docker is None:
            raise ProbeFailure("workspace_development_docker_boundary_missing")
        if "backend" not in self.docker.containers:
            self.docker.snapshot_source = receipt.snapshot_path
            self.docker.snapshot_digest = receipt.snapshot_digest
            self.docker.snapshot_bytes = receipt.snapshot_bytes
            self.docker.data_revision = self.spec.data_revision
            _invoke_gate(gate, operation_id)
            self.docker.create_backend()
            _invoke_gate(gate, operation_id)
            self.docker.start("backend")
            return
        actual = self.docker.inspect("backend")
        state = actual["State"]
        if state.get("Running") is True or state.get("Pid") not in (0, None):
            raise ProbeFailure("workspace_development_backend_must_be_stopped_before_replacement")
        mounts = actual.get("Mounts", [])
        old_snapshots = [item for item in mounts if item.get("Destination") == "/workspace-cache/dependencies.tar.gz"]
        old_revisions = [item.partition("=")[2] for item in actual.get("Config", {}).get("Env", [])
                         if item.startswith("CLOUDHELM_DATA_REVISION=")]
        if len(old_snapshots) != 1 or len(old_revisions) != 1:
            raise ProbeFailure("workspace_development_backend_configuration_unconfirmed")
        old_source = Path(old_snapshots[0].get("Source", ""))
        try:
            old_source.relative_to(Path(self.pinned_storage.cache_root))
        except ValueError:
            raise ProbeFailure("workspace_development_backend_snapshot_outside_cache") from None
        old_snapshot = self.docker.snapshot_source
        old_digest, old_bytes, old_revision = self.docker.snapshot_digest, self.docker.snapshot_bytes, self.docker.data_revision
        self.docker.snapshot_source = old_source
        self.docker.snapshot_digest, self.docker.snapshot_bytes = None, None
        self.docker.data_revision = old_revisions[0]
        self.docker.images = {
            "python": inspect_fixed_image(self.client, PYTHON_REFERENCE, PYTHON_IMAGE_DIGEST) or "",
            "postgres": self.docker.images.get("postgres", ""),
        }
        try:
            self.docker.verify_container("backend", require_running=False)
        except ProbeFailure:
            raise ProbeFailure("workspace_development_stopped_backend_boundary_unconfirmed") from None
        finally:
            self.docker.snapshot_source = old_snapshot
            self.docker.snapshot_digest, self.docker.snapshot_bytes = old_digest, old_bytes
            self.docker.data_revision = old_revision
        if (old_source == receipt.snapshot_path and old_revisions[0] == self.spec.data_revision):
            return
        _invoke_gate(gate, operation_id)
        self.docker.remove_exited("backend")
        self.docker.snapshot_source = receipt.snapshot_path
        self.docker.snapshot_digest = receipt.snapshot_digest
        self.docker.snapshot_bytes = receipt.snapshot_bytes
        self.docker.data_revision = self.spec.data_revision
        _invoke_gate(gate, operation_id)
        self.docker.create_backend()
        _invoke_gate(gate, operation_id)
        self.docker.start("backend")

    def start_existing(self, request, storage: EngineeringStorage, *, current_spec=None, gate=None
                       ) -> WorkspaceDevelopmentEnvironmentObservation:
        if self.docker is None:
            raise ProbeFailure("workspace_development_environment_not_discovered")
        spec, data_generation = self._current_spec_for_existing(request, current_spec)
        self._validate_spec(spec)
        self._hold_pin(storage)
        self._validate_storage(storage)
        self.spec, self.binding, self.data_generation = spec, spec.binding, data_generation
        source = self._open_workspace_files(storage, spec.binding)
        if source.manifest_digest != spec.source_manifest_digest:
            raise ProbeFailure("workspace_development_source_spec_stale")
        if self.group.lock is None:
            self._acquire_group(fresh=False)
        operation_id = request.operation_id
        self.latest_operation_id = operation_id
        self.latest_request_digest = workspace_development_operation_digest(request)
        if "backend" in self.docker.containers:
            backend = self.docker.inspect("backend")
            if backend["State"].get("Running") is True or backend["State"].get("Pid") not in (0, None):
                # Confirm the old backend stopped before preparing replacement dependencies.
                _invoke_gate(gate, operation_id)
                self.docker.stop("backend")
        receipt = self._prepare_dependencies(storage, spec, operation_id, gate)
        _invoke_gate(gate, operation_id)
        self.docker.ensure_images()
        self._validate_discovered_network()
        if "postgres" not in self.docker.containers:
            _invoke_gate(gate, operation_id)
            self.docker.create_database()
        else:
            self.docker.verify_container("postgres", require_running=False)
        if "backend" not in self.docker.containers:
            self.docker.snapshot_source = receipt.snapshot_path
            self.docker.snapshot_digest, self.docker.snapshot_bytes = receipt.snapshot_digest, receipt.snapshot_bytes
            self.docker.data_revision = spec.data_revision
            _invoke_gate(gate, operation_id)
            self.docker.create_backend()
        self.docker.snapshot_source = receipt.snapshot_path
        self.docker.snapshot_digest, self.docker.snapshot_bytes = receipt.snapshot_digest, receipt.snapshot_bytes
        self.docker.data_revision = spec.data_revision
        if self.docker.network_id is None:
            raise ProbeFailure("workspace_development_network_not_discovered")
        # A missing network can only be recreated when no saved container still refers to it.
        _invoke_gate(gate, operation_id)
        if "postgres" in self.docker.containers:
            self.docker.verify_container("postgres", require_running=False)
        self._replace_stale_backend(receipt, operation_id, gate)
        if not self.docker.inspect("postgres")["State"].get("Running"):
            _invoke_gate(gate, operation_id)
            self.docker.start("postgres")
        self._wait_database(storage, operation_id, gate)
        self._run_migration(storage, spec, operation_id, gate)
        self._prepare_data(spec, operation_id, gate)
        if not self.docker.inspect("backend")["State"].get("Running"):
            _invoke_gate(gate, operation_id)
            self.docker.start("backend")
        source, report, process_id, head = self._wait_ready(storage, spec, spec.source_manifest_digest)
        return self._ready_observation(operation_id, self.latest_request_digest, spec,
            source, report, process_id, head, data_generation)

    def observe_current(self, operation_id: str, request_digest: str,
                        current_spec: WorkspaceDevelopmentEnvironmentSpec, storage: EngineeringStorage, *,
                        prepare_operation_id: str | None = None
                        ) -> WorkspaceDevelopmentEnvironmentObservation | None:
        """Read current physical facts only; it never installs, starts, or repairs resources."""
        _safe_id(operation_id, r"workspace-dev-env-(prepare|suspend|resume|reset_data|dispose)-[0-9a-f]{32}",
                 "workspace_development_operation_id_invalid")
        _safe_id(request_digest, r"sha256:[0-9a-f]{64}", "workspace_development_request_digest_invalid")
        self._validate_spec(current_spec)
        self._hold_pin(storage)
        self._validate_storage(storage)
        self.spec, self.binding = current_spec, current_spec.binding
        source = observe_workspace_source(storage, current_spec.binding)
        if source.manifest_digest != current_spec.source_manifest_digest:
            return None
        if self.docker is None:
            selected_prepare = prepare_operation_id or self.prepare_operation_id
            if selected_prepare is None:
                return None
            try:
                self.discover(storage, prepare_operation_id=selected_prepare)
            except ProbeFailure:
                return None
        if self.docker is None or not {"postgres", "backend"}.issubset(self.docker.containers):
            return None
        try:
            dependency_input = PythonDependencyInput()
            seed = python_dependencies.verify_seed(
                python_dependencies.CACHE_ROOT / dependency_input.cache_key, dependency_input)
            source_files = read_workspace_backend_inputs(storage, current_spec.binding)
            inputs = validate_workspace_dependency_inputs(current_spec.binding, source_files,
                dependency_input=dependency_input, seed_receipt=seed, toolchain=WORKSPACE_PYTHON_TOOLCHAIN)
            directory = Path(storage.cache_root) / "workspace-python" / inputs.workspace_key / inputs.environment_key
            cache = PrivateRoot(directory)
            try:
                receipt = _cached_receipt(current_spec.binding, directory, cache.fd, inputs)
            finally:
                cache.close()
            self._verify_receipt(receipt, current_spec, storage)
            if receipt.snapshot_path != self.docker.snapshot_source:
                return None
            self.dependency_receipt = receipt
            self.docker.snapshot_digest, self.docker.snapshot_bytes = receipt.snapshot_digest, receipt.snapshot_bytes
            self.docker.data_revision = current_spec.data_revision
            self._acquire_group(fresh=False)
            python_image = inspect_fixed_image(self.client, PYTHON_REFERENCE, PYTHON_IMAGE_DIGEST)
            postgres_image = inspect_fixed_image(self.client, POSTGRES_REFERENCE, POSTGRES_IMAGE_DIGEST)
            if python_image is None or postgres_image is None:
                return None
            self.docker.images = {"python": python_image, "postgres": postgres_image}
            self._validate_discovered_network()
            if not self.docker.inspect("postgres")["State"].get("Running"):
                return None
            if not self.docker.inspect("backend")["State"].get("Running"):
                return None
            self.docker.verify_container("postgres")
            self.docker.verify_container("backend")
            head = self._migration_head()
            if head != current_spec.migration_revision:
                return None
            seed_count = self.docker.sql(
                seed_count_statement(current_spec.data_revision), required=False)
            if seed_count.returncode or seed_count.stdout.strip() != b"1":
                return None
            report = probe_workspace_backend(self.client, self.docker.containers["backend"])
            process_id = workspace_server_process_id(
                self.client, self.docker.containers["backend"], self.group.path)
            after = observe_workspace_source(storage, current_spec.binding)
            if after.manifest_digest != source.manifest_digest or after.source_path != source.source_path:
                return None
            if current_spec.data_generation < 1:
                return None
            return self._ready_observation(operation_id, request_digest, current_spec,
                after, report, process_id, head, current_spec.data_generation)
        except ProbeFailure as failure:
            if failure.category in {
                "workspace_python_cache_directory_invalid", "workspace_python_cache_members_mismatch",
                "workspace_python_cache_identity_mismatch", "workspace_python_cache_receipt_invalid",
                "workspace_development_http_probe_not_ready", "workspace_development_server_process_identity_unconfirmed",
            }:
                return None
            raise
        except (OSError, ValueError, WorkspaceFileError):
            return None

    def observe_stop(self, prepare_operation_id: str, binding: WorkspaceBinding,
                     storage: EngineeringStorage) -> WorkspaceDevelopmentStopFact | None:
        """Read-only stop reconciliation, including unknown readers of pinned paths."""
        _safe_id(prepare_operation_id, r"workspace-dev-env-prepare-[0-9a-f]{32}",
                 "workspace_development_prepare_operation_invalid")
        if not self._same_workspace(self.spec.binding, binding):
            raise ProbeFailure("workspace_development_stop_binding_mismatch")
        self._hold_pin(storage)
        self._validate_storage(storage)
        source = observe_workspace_source(storage, binding)
        scope_id = workspace_runtime_scope_id(binding)
        records = WorkspaceDevelopmentDocker.discover_owned(
            self.spec.environment_id, scope_id, operation_id=prepare_operation_id)
        identities = {item["container_id"] for item in records}
        if any(item["running"] or item["process_id"] not in (0, None)
               or item["paused"] or item["restarting"] for item in records):
            return None
        try:
            from modules.workspaces.candidate_freeze import _inventory
            from modules.workspaces.candidate_writers import overlaps

            protected = [source.source_path,
                str(Path(storage.workspace_root) / RUNTIME_DIRECTORY / self.spec.environment_id)]
            for item in _inventory():
                relevant = any(mount.get("Source", "").startswith("/") and any(
                    overlaps(os.path.realpath(mount["Source"]), target) for target in protected)
                    for mount in item["mounts"])
                if relevant and item["id"] not in identities:
                    return None
                if relevant and (item["status"] in {"running", "paused"} or item["pid"] not in (0, None)):
                    return None
        except (WorkspaceFileError, OSError, KeyError, TypeError):
            return None
        group_path = Path("/sys/fs/cgroup") / self.group.unit
        if (group_path / "cgroup.events").exists():
            if "populated 0" not in (group_path / "cgroup.events").read_text(encoding="utf-8").splitlines():
                return None
        runner = self._runner(prepare_operation_id, binding, source.manifest_digest,
            {"physical_stop_observed": True,
             "containers": sorted((item["container_id"], item["status"], item["process_id"]) for item in records),
             "workspace_manifest_digest": source.manifest_digest})
        return WorkspaceDevelopmentStopFact(outcome="confirmed_stopped", process_id=None,
            runner=runner, binding=binding)

    def prepare(self, request: PrepareWorkspaceDevelopmentEnvironment, storage: EngineeringStorage, *, gate=None
                ) -> WorkspaceDevelopmentEnvironmentObservation:
        if type(request) is not PrepareWorkspaceDevelopmentEnvironment:
            raise ProbeFailure("workspace_development_prepare_request_required")
        if (request.spec != self.spec or request.environment_id != self.spec.environment_id
                or request.binding != self.spec.binding):
            raise ProbeFailure("workspace_development_prepare_request_mismatch")
        self._validate_spec(self.spec)
        self._hold_pin(storage)
        self._validate_storage(storage)
        self.prepare_operation_id = request.operation_id
        self.latest_operation_id = request.operation_id
        self.latest_request_digest = workspace_development_operation_digest(request)
        _invoke_gate(gate, request.operation_id)
        self._open_runtime_directories(storage, create=True)
        source = self._open_workspace_files(storage, request.binding)
        if source.manifest_digest != self.spec.source_manifest_digest:
            raise ProbeFailure("workspace_development_prepare_source_digest_mismatch")
        _invoke_gate(gate, request.operation_id)
        self._make_client(create=True)
        self._acquire_group(fresh=True)
        _invoke_gate(gate, request.operation_id)
        receipt = self._prepare_dependencies(storage, self.spec, request.operation_id, gate)
        self._validate_spec(self.spec)
        source = observe_workspace_source(storage, request.binding)
        if source.manifest_digest != self.spec.source_manifest_digest:
            raise ProbeFailure("workspace_development_prepare_source_changed")
        _invoke_gate(gate, request.operation_id)
        self.docker = None
        docker = self._make_docker(receipt)
        docker.ensure_images()
        _invoke_gate(gate, request.operation_id)
        docker.create_network()
        _invoke_gate(gate, request.operation_id)
        docker.create_database()
        _invoke_gate(gate, request.operation_id)
        docker.start("postgres")
        self._wait_database(storage, request.operation_id, gate)
        self._run_migration(storage, self.spec, request.operation_id, gate)
        self._prepare_data(self.spec, request.operation_id, gate)
        _invoke_gate(gate, request.operation_id)
        docker.create_backend()
        _invoke_gate(gate, request.operation_id)
        docker.start("backend")
        source, report, process_id, head = self._wait_ready(storage, self.spec,
            self.spec.source_manifest_digest)
        data_generation = max(1, self.spec.data_generation + 1)
        result = self._ready_observation(request.operation_id, self.latest_request_digest,
            self.spec, source, report, process_id, head, data_generation)
        return result

    def refresh(self, operation_id: str, request_digest: str,
                current_spec: WorkspaceDevelopmentEnvironmentSpec, storage: EngineeringStorage, *, gate=None
                ) -> WorkspaceDevelopmentEnvironmentObservation:
        _safe_id(operation_id,
            r"workspace-dev-env-(prepare|suspend|resume|reset_data|dispose)-[0-9a-f]{32}",
            "workspace_development_operation_id_invalid")
        _safe_id(request_digest, r"sha256:[0-9a-f]{64}", "workspace_development_request_digest_invalid")
        self._validate_spec(current_spec)
        if self.state != "ready" or self.docker is None:
            raise ProbeFailure("workspace_development_refresh_requires_ready")
        if not self._same_workspace(self.binding, current_spec.binding):
            raise ProbeFailure("workspace_development_refresh_workspace_changed")
        self._hold_pin(storage)
        self._validate_storage(storage)
        source = self._open_workspace_files(storage, current_spec.binding)
        if source.manifest_digest != current_spec.source_manifest_digest:
            raise ProbeFailure("workspace_development_refresh_source_spec_stale")
        previous_digest, previous_process = self.last_source_digest, self.last_process_id
        if self.group.lock is None:
            self._acquire_group(fresh=False)
        old_snapshot = self.dependency_receipt.snapshot_digest if self.dependency_receipt else None
        receipt = self._prepare_dependencies(storage, current_spec, operation_id, gate)
        self.spec, self.binding = current_spec, current_spec.binding
        docker = self._make_docker(receipt)
        if old_snapshot is not None and receipt.snapshot_digest != old_snapshot:
            state = docker.inspect("backend")["State"]
            if state.get("Running") is True or state.get("Pid") not in (0, None):
                _invoke_gate(gate, operation_id)
                docker.stop("backend")
            _invoke_gate(gate, operation_id)
            docker.remove_exited("backend")
            _invoke_gate(gate, operation_id)
            docker.create_backend()
            _invoke_gate(gate, operation_id)
            docker.start("backend")
        source, report, process_id, head = self._wait_ready(storage, current_spec,
            current_spec.source_manifest_digest, previous_process_id=previous_process,
            require_reload=(previous_digest != current_spec.source_manifest_digest and old_snapshot == receipt.snapshot_digest))
        result = self._ready_observation(operation_id, request_digest, current_spec,
            source, report, process_id, head, self.data_generation)
        return result

    def stop_services(self, storage: EngineeringStorage, *, gate=None) -> WorkspaceDevelopmentStopFact:
        if self.docker is None or self.prepare_operation_id is None or self.group.path is None:
            raise ProbeFailure("workspace_development_runtime_not_discovered")
        operation_id = self.latest_operation_id or self.prepare_operation_id
        self._hold_pin(storage)
        self._validate_storage(storage)
        if self.group.lock is None:
            self._acquire_group(fresh=False)
        app_process = None
        try:
            if "backend" in self.docker.containers:
                try:
                    app_process = workspace_server_process_id(self.client, self.docker.containers["backend"],
                                                              self.group.path)
                except ProbeFailure:
                    app_process = None
            for role in ("backend", "migration", "postgres"):
                if role in self.docker.containers:
                    _invoke_gate(gate, operation_id)
                    self.docker.stop(role)
            self.group.dispose()
            source = observe_workspace_source(storage, self.binding)
            runner = self._runner(operation_id, self.binding,
                source.manifest_digest,
                {"stop_confirmed": True, "process_id": app_process,
                 "container_ids": sorted(self.docker.containers.values())})
            return WorkspaceDevelopmentStopFact(outcome="confirmed_stopped", process_id=app_process,
                runner=runner, binding=self.binding)
        except ProbeFailure:
            raise
        except Exception:
            raise ProbeFailure("workspace_development_stop_unconfirmed") from None

    def stop(self, request: DisposeWorkspaceDevelopmentEnvironment, storage: EngineeringStorage, *, gate=None
             ) -> WorkspaceDevelopmentEnvironmentObservation:
        if type(request) is not DisposeWorkspaceDevelopmentEnvironment:
            raise ProbeFailure("workspace_development_dispose_request_required")
        if (request.environment_id != self.spec.environment_id
                or not self._same_workspace(self.binding, request.binding)):
            raise ProbeFailure("workspace_development_dispose_request_mismatch")
        self._hold_pin(storage)
        self._validate_storage(storage)
        self.binding = request.binding
        if self.docker is None:
            self.discover(storage, prepare_operation_id=self.prepare_operation_id)
        if self.group.lock is None:
            self._acquire_group(fresh=False)
        _invoke_gate(gate, request.operation_id)
        try:
            app_process = None
            if self.docker is not None and "backend" in self.docker.containers:
                try:
                    app_process = workspace_server_process_id(self.client, self.docker.containers["backend"],
                                                              self.group.path)
                except ProbeFailure:
                    pass
            for role in ("backend", "migration", "postgres"):
                if role in self.docker.containers:
                    _invoke_gate(gate, request.operation_id)
                    self.docker.stop(role)
                    _invoke_gate(gate, request.operation_id)
                    self.docker.remove_exited(role)
            _invoke_gate(gate, request.operation_id)
            self.docker.remove_network()
            self.group.dispose()
            source = observe_workspace_source(storage, self.binding)
            if self.pin is not None:
                self.pin.observe()
            runner = self._runner(request.operation_id, self.binding, source.manifest_digest,
                {"physical_stop_confirmed": True, "app_process_id": app_process,
                 "containers_removed": True, "network_removed": True})
            stop_fact = WorkspaceDevelopmentStopFact(outcome="confirmed_stopped", process_id=app_process,
                runner=runner, binding=self.binding)
            runtime = WorkspaceDevelopmentRuntimeFact(status="stopped", process_id=None, runner=runner,
                binding=self.binding, source_manifest_digest=source.manifest_digest)
            result = WorkspaceDevelopmentEnvironmentObservation(
                environment_id=self.spec.environment_id, operation_id=request.operation_id,
                request_digest=workspace_development_operation_digest(request), binding=self.binding,
                storage_ref=self.spec.storage_ref, source_manifest_digest=source.manifest_digest,
                migration_revision=self.spec.migration_revision, data_revision=self.spec.data_revision,
                data_generation=self.data_generation, state="disposed", runtime_fact=runtime,
                stop_fact=stop_fact)
            self.observations[request.operation_id] = result
            self.latest_operation_id = request.operation_id
            self.latest_request_digest = result.request_digest
            self.state = "disposed"
            self._release_pin()
            self._close_fds()
            _ACTIVE_RUNTIMES.pop(self.spec.environment_id, None)
            return result
        except ProbeFailure:
            raise
        except Exception:
            raise ProbeFailure("workspace_development_dispose_unconfirmed") from None

    def query(self, operation_id: str) -> WorkspaceDevelopmentEnvironmentObservation:
        value = self.observations.get(operation_id)
        if type(value) is not WorkspaceDevelopmentEnvironmentObservation:
            raise ProbeFailure("workspace_development_observation_unavailable")
        return value

    def registered_readers(self, binding: WorkspaceBinding | None = None) -> tuple[RegisteredWorkspaceReader, ...]:
        selected = binding or self.binding
        if not self._same_workspace(self.binding, selected):
            raise ProbeFailure("workspace_development_reader_binding_mismatch")
        if self.docker is None:
            return ()
        return self.docker.registered_readers()

    def probe_devmarker(self, storage: EngineeringStorage, binding: WorkspaceBinding | None = None) -> dict:
        selected = binding or self.binding
        source = observe_workspace_source(storage, selected)
        if self.docker is None or "backend" not in self.docker.containers:
            raise ProbeFailure("workspace_development_backend_not_registered")
        report = probe_workspace_backend(self.client, self.docker.containers["backend"])
        after = observe_workspace_source(storage, selected)
        if (source.manifest_digest != after.manifest_digest or source.source_path != after.source_path):
            raise ProbeFailure("workspace_development_probe_source_unstable")
        process_id = workspace_server_process_id(self.client, self.docker.containers["backend"], self.group.path)
        return {"status": report["devmarker_status"], "response_digest": report["devmarker_digest"],
                "source_manifest_digest": source.manifest_digest, "process_id": process_id}

    def probe_notes(self, storage: EngineeringStorage, binding: WorkspaceBinding | None = None) -> dict:
        selected = binding or self.binding
        source = observe_workspace_source(storage, selected)
        if self.docker is None or "backend" not in self.docker.containers:
            raise ProbeFailure("workspace_development_backend_not_registered")
        report = probe_workspace_backend(self.client, self.docker.containers["backend"])
        after = observe_workspace_source(storage, selected)
        if (source.manifest_digest != after.manifest_digest or source.source_path != after.source_path):
            raise ProbeFailure("workspace_development_probe_source_unstable")
        process_id = workspace_server_process_id(self.client, self.docker.containers["backend"], self.group.path)
        return {"response_digest": report["notes_digest"], "notes": report["notes"],
                "source_manifest_digest": source.manifest_digest, "process_id": process_id}

    @classmethod
    def probe_registered_environment(cls, spec: WorkspaceDevelopmentEnvironmentSpec,
            prepare_operation_id: str, storage: EngineeringStorage, binding: WorkspaceBinding, *, kind: str) -> dict:
        """Run only a fixed GET probe against an already registered local environment."""
        if kind not in {"devmarker", "notes"} or not cls._same_workspace(spec.binding, binding):
            raise ProbeFailure("workspace_development_validation_probe_scope_invalid")
        runtime = cls(spec)
        try:
            runtime.discover(storage, prepare_operation_id=prepare_operation_id)
            if kind == "devmarker":
                return runtime.probe_devmarker(storage, binding)
            return runtime.probe_notes(storage, binding)
        finally:
            runtime._release_pin()
            runtime._close_fds()

    def close(self) -> None:
        """Release trusted local handles only after every known container is confirmed stopped."""
        if self.docker is not None:
            for role in tuple(self.docker.containers):
                value = self.docker.inspect(role)
                state = value.get("State", {})
                if state.get("Running") is True or state.get("Pid") not in (0, None):
                    raise ProbeFailure("workspace_development_close_requires_confirmed_stop")
        if self.group.lock is not None:
            self.group.dispose()
        self._release_pin()
        self._close_fds()

    def _release_pin(self) -> None:
        if self.pin_context is not None:
            try:
                self.pin_context.__exit__(None, None, None)
            except Exception:
                raise ProbeFailure("workspace_development_storage_pin_release_unconfirmed") from None
        self.pin_context = self.pin = None
        self.pinned_storage = None

    def _close_fds(self) -> None:
        for name in ("_workspace_files_fd", "_secrets_fd", "_database_fd", "_runtime_fd"):
            descriptor = getattr(self, name)
            if descriptor >= 0:
                os.close(descriptor)
                setattr(self, name, -1)
        if self._workspace_root is not None:
            self._workspace_root.close()
            self._workspace_root = None

    @staticmethod
    def _same_workspace(left: WorkspaceBinding, right: WorkspaceBinding) -> bool:
        fixed = ("workspace_id", "project_id", "task_id", "work_item_id", "owner_user_id",
                 "source_id", "source_revision", "base_commit")
        return all(getattr(left, field) == getattr(right, field) for field in fixed)
