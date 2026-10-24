"""Private, bounded journal for mutable Workspace development operations."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

import rfc8785

from modules.workspaces.safe_paths import (
    PrivateRoot, WorkspaceFileError, exists_at, read_regular,
)
from packages.contracts.p1.development_environment import (
    DisposeWorkspaceDevelopmentEnvironment, PrepareWorkspaceDevelopmentEnvironment,
    ResetWorkspaceDevelopmentData, ResumeWorkspaceDevelopmentEnvironment,
    SuspendWorkspaceDevelopmentEnvironment, WorkspaceDevelopmentEnvironmentObservation,
    WorkspaceDevelopmentEnvironmentOperationIntent, workspace_development_operation_digest,
)
from packages.contracts.p1.workspace_git import content_digest

from .toolchain import ProbeFailure

JOURNAL_SCHEMA = "p1-workspace-development-journal-r1"
JOURNAL_DIRECTORY = "workspace-development-journal"
MAX_RECORD_BYTES = 65536
MAX_ENVIRONMENT_OPERATIONS = 128
_ENVIRONMENT_ID = re.compile(r"^dev-env-[0-9a-f]{32}$")
_OPERATION_ID = re.compile(r"^workspace-dev-env-(prepare|suspend|resume|reset_data|dispose)-[0-9a-f]{32}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUEST_TYPES = {
    "prepare": PrepareWorkspaceDevelopmentEnvironment,
    "suspend": SuspendWorkspaceDevelopmentEnvironment,
    "resume": ResumeWorkspaceDevelopmentEnvironment,
    "reset_data": ResetWorkspaceDevelopmentData,
    "dispose": DisposeWorkspaceDevelopmentEnvironment,
}


def observation_digest(observation: WorkspaceDevelopmentEnvironmentObservation) -> str:
    return content_digest(rfc8785.dumps(observation.model_dump(mode="json")))


def validated_intent(value) -> WorkspaceDevelopmentEnvironmentOperationIntent:
    if type(value) is not WorkspaceDevelopmentEnvironmentOperationIntent:
        raise ProbeFailure("workspace_development_intent_required")
    try:
        intent = WorkspaceDevelopmentEnvironmentOperationIntent.model_validate(value.model_dump(mode="python"))
    except (TypeError, ValueError):
        raise ProbeFailure("workspace_development_intent_invalid") from None
    if (type(intent.request) is not _REQUEST_TYPES.get(intent.request.action)
            or intent.request_digest != workspace_development_operation_digest(intent.request)):
        raise ProbeFailure("workspace_development_intent_invalid")
    return intent


def operation_intent(record: dict, operation_id: str) -> WorkspaceDevelopmentEnvironmentOperationIntent:
    try:
        intent = WorkspaceDevelopmentEnvironmentOperationIntent.model_validate(record["intent"])
    except (KeyError, TypeError, ValueError):
        raise ProbeFailure("workspace_development_journal_intent_invalid") from None
    if (intent.request.operation_id != operation_id or intent.request_digest != record.get("request_digest")
            or intent.request_digest != workspace_development_operation_digest(intent.request)
            or type(intent.request) is not _REQUEST_TYPES.get(intent.request.action)):
        raise ProbeFailure("workspace_development_journal_intent_mismatch")
    return intent


def observation(record: dict) -> WorkspaceDevelopmentEnvironmentObservation | None:
    raw = record.get("observation_json")
    if raw is None:
        return None
    try:
        value = WorkspaceDevelopmentEnvironmentObservation.model_validate(raw)
    except (TypeError, ValueError):
        raise ProbeFailure("workspace_development_journal_observation_invalid") from None
    if record.get("observation_digest") != observation_digest(value):
        raise ProbeFailure("workspace_development_journal_observation_digest_mismatch")
    return value


class WorkspaceDevelopmentJournalError(RuntimeError):
    """Only fixed journal errors cross the Runner boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _json_bytes(value: dict) -> bytes:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > MAX_RECORD_BYTES:
        raise WorkspaceDevelopmentJournalError("workspace_development_journal_record_too_large")
    return raw


def _safe_environment(environment_id: str) -> None:
    if not isinstance(environment_id, str) or _ENVIRONMENT_ID.fullmatch(environment_id) is None:
        raise WorkspaceDevelopmentJournalError("workspace_development_environment_identity_invalid")


def _safe_operation(operation_id: str) -> None:
    if not isinstance(operation_id, str) or _OPERATION_ID.fullmatch(operation_id) is None:
        raise WorkspaceDevelopmentJournalError("workspace_development_operation_identity_invalid")


def _storage_root(storage) -> Path:
    try:
        storage.observe()
        admission = storage.admission
        root = Path(storage.cache_root)
        expected = admission.directory.parent / "cache"
        if (root != expected or os.stat(root).st_dev != os.fstat(admission.directory_fd).st_dev
                or admission.snapshot.purpose != "workspace"):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_storage_mismatch")
        return root
    except WorkspaceDevelopmentJournalError:
        raise
    except (OSError, AttributeError, TypeError):
        raise WorkspaceDevelopmentJournalError("workspace_development_journal_storage_unavailable") from None


def _write_atomic(parent: int, name: str, value: dict) -> None:
    payload = _json_bytes(value)
    stage = ".journal-stage-" + uuid.uuid4().hex
    descriptor = -1
    try:
        descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
        if os.getuid() == 0:
            os.fchown(descriptor, 1000, 1000)
        state = os.fstat(descriptor)
        if (not stat.S_ISREG(state.st_mode) or state.st_uid != 1000 or state.st_mode & 0o077
                or state.st_nlink != 1):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_file_unsafe")
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise WorkspaceDevelopmentJournalError("workspace_development_journal_write_failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(stage, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    except WorkspaceDevelopmentJournalError:
        raise
    except OSError:
        raise WorkspaceDevelopmentJournalError("workspace_development_journal_write_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(stage, dir_fd=parent)
        except FileNotFoundError:
            pass
        except OSError:
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_stage_cleanup_failed") from None


class _JournalSession:
    def __init__(self, root: int, environment_id: str):
        self.root, self.environment_id = root, environment_id
        self.environment_name = "environment-" + environment_id + ".json"

    def read_environment(self) -> dict | None:
        if not exists_at(self.root, self.environment_name):
            return None
        try:
            value = json.loads(read_regular(self.root, self.environment_name, MAX_RECORD_BYTES).decode("utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, WorkspaceFileError):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_environment_invalid") from None
        operation_ids = value.get("operation_ids") if isinstance(value, dict) else None
        if (not isinstance(value, dict) or value.get("environment_id") != self.environment_id
                or value.get("schema_revision") != JOURNAL_SCHEMA
                or not isinstance(operation_ids, list) or len(operation_ids) > MAX_ENVIRONMENT_OPERATIONS
                or any(not isinstance(item, str) or _OPERATION_ID.fullmatch(item) is None for item in operation_ids)
                or len(set(operation_ids)) != len(operation_ids)):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_environment_invalid")
        return value

    def write_environment(self, value: dict) -> None:
        if value.get("environment_id") != self.environment_id:
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_environment_mismatch")
        operations = value.get("operation_ids")
        if (not isinstance(operations, list) or len(operations) > MAX_ENVIRONMENT_OPERATIONS
                or any(not isinstance(item, str) or _OPERATION_ID.fullmatch(item) is None for item in operations)
                or len(set(operations)) != len(operations)):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_operation_limit")
        _write_atomic(self.root, self.environment_name, value)

    def read_operation(self, operation_id: str) -> dict | None:
        _safe_operation(operation_id)
        name = "operation-" + operation_id + ".json"
        if not exists_at(self.root, name):
            return None
        try:
            value = json.loads(read_regular(self.root, name, MAX_RECORD_BYTES).decode("utf-8"))
        except (ValueError, WorkspaceFileError):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_operation_invalid") from None
        identity = _OPERATION_ID.fullmatch(operation_id)
        if (not isinstance(value, dict) or value.get("operation_id") != operation_id
                or value.get("schema_revision") != JOURNAL_SCHEMA
                or value.get("action") != identity.group(1)
                or not isinstance(value.get("request_digest"), str)
                or _DIGEST.fullmatch(value["request_digest"]) is None
                or not isinstance(value.get("environment_id"), str)
                or _ENVIRONMENT_ID.fullmatch(value["environment_id"]) is None):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_operation_invalid")
        return value

    def write_operation(self, value: dict) -> None:
        operation_id = value.get("operation_id")
        _safe_operation(operation_id)
        identity = _OPERATION_ID.fullmatch(operation_id)
        if (value.get("environment_id") != self.environment_id or value.get("action") != identity.group(1)
                or not isinstance(value.get("request_digest"), str)
                or _DIGEST.fullmatch(value["request_digest"]) is None):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_operation_mismatch")
        _write_atomic(self.root, "operation-" + operation_id + ".json", value)


class WorkspaceDevelopmentJournal:
    """Store operation identities outside removable environment runtime data."""

    def __init__(self, storage):
        self.storage = storage
        self.root_path = _storage_root(storage) / JOURNAL_DIRECTORY

    @contextmanager
    def _root(self, *, create: bool):
        parent = None
        root = None
        try:
            parent = PrivateRoot(self.root_path.parent)
            if create:
                try:
                    os.mkdir(JOURNAL_DIRECTORY, 0o700, dir_fd=parent.fd)
                    os.fsync(parent.fd)
                except FileExistsError:
                    pass
            try:
                root = os.open(JOURNAL_DIRECTORY,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent.fd)
            except FileNotFoundError:
                if create:
                    raise WorkspaceDevelopmentJournalError("workspace_development_journal_unavailable") from None
            if root is not None:
                if create:
                    if os.getuid() == 0:
                        os.fchown(root, 1000, 1000)
                    os.fchmod(root, 0o700)
                state = os.fstat(root)
                if (state.st_dev != os.fstat(self.storage.admission.directory_fd).st_dev
                        or state.st_uid != 1000 or state.st_mode & 0o077):
                    raise WorkspaceDevelopmentJournalError("workspace_development_journal_storage_mismatch")
        except WorkspaceDevelopmentJournalError:
            if root is not None:
                os.close(root)
            if parent is not None:
                parent.close()
            raise
        except (OSError, WorkspaceFileError):
            if root is not None:
                os.close(root)
            if parent is not None:
                parent.close()
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_unavailable") from None
        if root is None:
            parent.close()
            yield None
            return
        try:
            yield root
        finally:
            os.close(root)
            parent.close()

    @contextmanager
    def environment(self, environment_id: str):
        _safe_environment(environment_id)
        try:
            with self._root(create=True) as root:
                lock_name = "lock-" + environment_id
                lock = os.open(lock_name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                               dir_fd=root)
                try:
                    if os.getuid() == 0:
                        os.fchown(lock, 1000, 1000)
                    os.fchmod(lock, 0o600)
                    lock_state = os.fstat(lock)
                    if (not stat.S_ISREG(lock_state.st_mode) or lock_state.st_uid != 1000
                            or lock_state.st_mode & 0o077 or lock_state.st_nlink != 1):
                        raise WorkspaceDevelopmentJournalError("workspace_development_journal_lock_unsafe")
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    yield _JournalSession(root, environment_id)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    os.close(lock)
        except WorkspaceDevelopmentJournalError:
            raise
        except (OSError, WorkspaceFileError):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_unavailable") from None

    def operation(self, operation_id: str) -> dict | None:
        _safe_operation(operation_id)
        name = "operation-" + operation_id + ".json"
        try:
            with self._root(create=False) as root:
                if root is None or not exists_at(root, name):
                    return None
                value = json.loads(read_regular(root, name, MAX_RECORD_BYTES).decode("utf-8"))
        except (ValueError, OSError, WorkspaceFileError):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_operation_invalid") from None
        identity = _OPERATION_ID.fullmatch(operation_id)
        if (not isinstance(value, dict) or value.get("operation_id") != operation_id
                or value.get("schema_revision") != JOURNAL_SCHEMA
                or value.get("action") != identity.group(1)
                or not isinstance(value.get("request_digest"), str)
                or _DIGEST.fullmatch(value["request_digest"]) is None
                or not isinstance(value.get("environment_id"), str)
                or _ENVIRONMENT_ID.fullmatch(value["environment_id"]) is None):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_operation_invalid")
        return value

    def environment_ids(self) -> tuple[str, ...]:
        try:
            with self._root(create=False) as root:
                if root is None:
                    return ()
                names = os.listdir(root)
        except (OSError, WorkspaceFileError):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_unavailable") from None
        values = tuple(sorted(name[len("environment-"):-len(".json")]
                              for name in names if name.startswith("environment-") and name.endswith(".json")))
        if any(_ENVIRONMENT_ID.fullmatch(item) is None for item in values):
            raise WorkspaceDevelopmentJournalError("workspace_development_journal_environment_invalid")
        return values

    def read_environment(self, environment_id: str) -> dict | None:
        with self.environment(environment_id) as journal:
            return journal.read_environment()
