"""Closed local engineering composition; public requests never choose host paths."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p1.development_storage import DevelopmentStorageRef

from .development_storage import DevelopmentStorage

REGISTRY_ENV = "CLOUDHELM_ENGINEERING_REGISTRY_FILE"
SCOPE = "cloudhelm-wsl-controlled-development-r1"
REPOSITORY = Path(__file__).resolve().parents[2]
NPM_DOWNLOAD_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/npm-download-seed")
NPM_MANIFEST = "sha256:1763287887271b7713a4d0764739b73bf592d37b6cab85535546d0b3f15c98d0"


class EngineeringRegistryError(ValueError):
    pass


class EngineeringRegistration(Contract):
    schema_revision: Literal["p1-engineering-registration-r1"] = "p1-engineering-registration-r1"
    scope: Literal[SCOPE] = SCOPE
    storage: DevelopmentStorageRef
    repository_seed_ref: Literal["cloudhelm-reference-r1"] = "cloudhelm-reference-r1"
    npm_seed_ref: Literal["reference-notes-npm-r1"] = "reference-notes-npm-r1"
    python_seed_ref: Literal["reference-notes-python-r1"] = "reference-notes-python-r1"

    @model_validator(mode="after")
    def check_storage(self):
        if self.storage.purpose != "workspace":
            raise ValueError("engineering_workspace_storage_reference_required")
        return self


def load_registration(path: str | os.PathLike[str] | None = None) -> EngineeringRegistration | None:
    """Read only this secret-free registration schema, never an application config."""
    selected = path if path is not None else os.environ.get(REGISTRY_ENV)
    if selected is None:
        return None
    descriptor = -1
    try:
        descriptor = os.open(selected, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_mode & 0o077 or before.st_nlink != 1 or before.st_size > 65536):
            raise EngineeringRegistryError("engineering_registry_not_private")
        raw = os.read(descriptor, 65537)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                                  value.st_ctime_ns, value.st_uid, value.st_mode, value.st_nlink)
        if identity(after) != identity(before) or len(raw) != before.st_size:
            raise EngineeringRegistryError("engineering_registry_changed")
        return EngineeringRegistration.model_validate_json(raw)
    except (OSError, ValueError):
        raise EngineeringRegistryError("engineering_registry_invalid_or_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@dataclass(frozen=True)
class EngineeringStorage:
    admission: object
    git_root: Path
    workspace_root: Path
    cache_root: Path
    archive_root: Path

    def observe(self):
        return self.admission.observe()


class EngineeringRegistry:
    def __init__(self, registration: EngineeringRegistration | None):
        if registration is not None and type(registration) is not EngineeringRegistration:
            raise EngineeringRegistryError("engineering_registration_required")
        self.registration = registration
        self._active = ContextVar("cloudhelm_engineering_storage", default=None)

    @contextmanager
    def admit(self, requested_bytes: int):
        if self.registration is None:
            raise EngineeringRegistryError("engineering_execution_not_configured")
        if self._active.get() is not None:
            raise EngineeringRegistryError("engineering_storage_admission_nested")
        reference = self.registration.storage
        with DevelopmentStorage(reference.storage_id).admit_ref(reference, requested_bytes=requested_bytes) as admitted:
            registration = admitted.snapshot.registration
            if (registration.scope != "local_controlled_development"
                    or not {"git", "workspace", "candidate", "cache", "archive"}.issubset(registration.allowed_purposes)):
                raise EngineeringRegistryError("engineering_storage_scope_unsupported")
            data = admitted.directory.parent
            roots = {purpose: data / purpose for purpose in ("git", "workspace", "cache", "archive")}
            for root in roots.values():
                descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    state = os.fstat(descriptor)
                    if (state.st_dev != os.fstat(admitted.directory_fd).st_dev
                            or state.st_uid != os.getuid() or state.st_mode & 0o077
                            or os.readlink(f"/proc/self/fd/{descriptor}") != str(root)):
                        raise EngineeringRegistryError("engineering_storage_root_mismatch")
                finally:
                    os.close(descriptor)
            storage = EngineeringStorage(admitted, roots["git"], roots["workspace"], roots["cache"], roots["archive"])
            token = self._active.set(storage)
            try:
                yield storage
                storage.observe()
            finally:
                self._active.reset(token)

    def current_storage(self) -> EngineeringStorage:
        storage = self._active.get()
        if storage is None:
            raise EngineeringRegistryError("engineering_storage_admission_required")
        storage.observe()
        return storage
