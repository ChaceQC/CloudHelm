"""FD-bound admission to one registered, fixed-size local development filesystem."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.p1.development_storage import (
    DevelopmentStorageRef, DevelopmentStorageRegistration, DevelopmentStorageSnapshot, StoragePurpose,
)

ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/development-storage")
METHOD = "p1-development-storage-r2"
FIXTURE_BYTES = 32 * 1024**2
SAFETY_BYTES = 1024**2
UID = 1000
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
PURPOSE_DIRECTORIES = {"git": "git", "workspace": "workspace", "candidate": "workspace",
                       "cache": "cache", "archive": "archive", "fixture": "fixture"}


class DevelopmentStorageError(RuntimeError):
    """Fixed categories only; never echo arbitrary filesystem or command output."""


def directory_at(parent: int, name: str, *, create: bool = False, private: bool = True) -> int:
    validate_name(name)
    created = False
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            created = True
        except FileExistsError:
            pass
    descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
    if created:
        os.fchown(descriptor, UID, UID)
    state = os.fstat(descriptor)
    if state.st_uid not in ((UID,) if private else (0, UID)) or state.st_mode & (0o077 if private else 0o022):
        os.close(descriptor)
        raise DevelopmentStorageError("storage_directory_not_owned_or_private")
    return descriptor


def root_descriptor(*, create: bool = False) -> int:
    descriptor = os.open("/", DIRECTORY_FLAGS)
    try:
        for part in ROOT.parts[1:]:
            child = directory_at(descriptor, part, create=create and part == ROOT.name,
                                 private=part == ROOT.name)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def regular_at(parent: int, name: str, *, flags: int = os.O_RDONLY, create: bool = False) -> int:
    validate_name(name)
    descriptor = os.open(name, flags | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
                         | (os.O_CREAT | os.O_EXCL if create else 0), 0o600, dir_fd=parent)
    if create and os.getuid() == 0:
        os.fchown(descriptor, UID, UID)
    state = os.fstat(descriptor)
    if (not stat.S_ISREG(state.st_mode) or state.st_uid != UID or state.st_mode & 0o077
            or state.st_nlink != 1):
        os.close(descriptor)
        raise DevelopmentStorageError("storage_file_not_private_regular_single_link")
    return descriptor


def read_json(parent: int, name: str) -> dict:
    descriptor = regular_at(parent, name)
    try:
        value = os.read(descriptor, 65537)
        if len(value) > 65536:
            raise DevelopmentStorageError("storage_metadata_too_large")
        return json.loads(value.decode("utf-8"))
    finally:
        os.close(descriptor)


def save_json(parent: int, name: str, value: dict) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > 65536:
        raise DevelopmentStorageError("storage_metadata_too_large")
    descriptor = regular_at(parent, name, flags=os.O_WRONLY, create=True)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
        os.fsync(parent)
    finally:
        os.close(descriptor)


def validate_id(storage_id: str) -> None:
    if not re.fullmatch(r"dev-storage-[a-f0-9]{32}", storage_id):
        raise DevelopmentStorageError("storage_identity_invalid")


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\x00" in name:
        raise DevelopmentStorageError("storage_component_invalid")


@contextmanager
def instance_descriptors(storage_id: str):
    validate_id(storage_id)
    root = root_descriptor()
    instance = None
    try:
        instance = directory_at(root, storage_id)
        if os.readlink(f"/proc/self/fd/{instance}") != str(ROOT / storage_id):
            raise DevelopmentStorageError("storage_instance_path_replaced")
        yield root, instance
    except OSError:
        raise DevelopmentStorageError("storage_instance_unavailable") from None
    finally:
        if instance is not None:
            os.close(instance)
        os.close(root)


@contextmanager
def instance_lock(instance: int):
    descriptor = regular_at(instance, "admission.lock", flags=os.O_RDWR)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DevelopmentStorageError("storage_admission_busy") from None
        yield
    finally:
        os.close(descriptor)


def mounted_identity(data: int, storage_id: str) -> dict:
    expected = str(ROOT / storage_id / "data")
    state = os.fstat(data)
    device = f"{os.major(state.st_dev)}:{os.minor(state.st_dev)}"
    if state.st_uid != UID or state.st_mode & 0o077:
        raise DevelopmentStorageError("storage_directory_not_owned_or_private")
    if os.readlink(f"/proc/self/fd/{data}") != expected:
        raise DevelopmentStorageError("storage_mount_path_replaced")
    matches, extra_mount = [], False
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if (fields[4].startswith(expected + "/")
                or (fields[2] == device and fields[4] != expected)):
            extra_mount = True
        if fields[4] == expected and fields[2] == device:
            separator = fields.index("-")
            matches.append((fields, separator))
    if len(matches) != 1:
        raise DevelopmentStorageError("storage_dedicated_mount_missing")
    if extra_mount:
        raise DevelopmentStorageError("storage_nested_or_duplicate_mount_unsupported")
    fields, separator = matches[0]
    options = set(fields[5].split(",")) | set(fields[separator + 3].split(","))
    source = fields[separator + 2]
    if (fields[3] != "/" or fields[separator + 1] != "ext4"
            or not re.fullmatch(r"/dev/loop[0-9]+", source)
            or "ro" in options or not {"rw", "nosuid", "nodev", "noexec"}.issubset(options)):
        raise DevelopmentStorageError("storage_mount_boundary_mismatch")
    loop = Path("/sys/dev/block") / device / "loop"
    if (loop.joinpath("backing_file").read_text(encoding="utf-8").strip() != str(ROOT / storage_id / "volume.ext4")
            or loop.joinpath("offset").read_text(encoding="utf-8").strip() != "0"
            or loop.joinpath("sizelimit").read_text(encoding="utf-8").strip() != "0"
            or loop.joinpath("autoclear").read_text(encoding="utf-8").strip() != "1"):
        raise DevelopmentStorageError("storage_loop_backing_mismatch")
    return {"mount_id": int(fields[0]), "mount_source": source, "mount_device": device,
            "mount_namespace": os.readlink("/proc/self/ns/mnt"),
            "mount_options": tuple(sorted(options)), "source_directory": expected}


def registration_at(instance: int, storage_id: str) -> DevelopmentStorageRegistration:
    try:
        registration = DevelopmentStorageRegistration.model_validate(read_json(instance, "registration.json"))
    except (ValueError, TypeError):
        raise DevelopmentStorageError("storage_registration_invalid_or_unsupported") from None
    if registration.storage_id != storage_id:
        raise DevelopmentStorageError("storage_registration_identity_mismatch")
    descriptor = regular_at(instance, "volume.ext4")
    try:
        state = os.fstat(descriptor)
        superblock = os.pread(descriptor, 120, 1024)
        if (state.st_dev != registration.backing_device or state.st_ino != registration.backing_inode
                or state.st_size != registration.backing_file_bytes
                or state.st_blocks * 512 < state.st_size or superblock[56:58] != b"\x53\xef"
                or str(uuid.UUID(bytes=superblock[104:120])) != registration.filesystem_uuid):
            raise DevelopmentStorageError("storage_backing_identity_or_capacity_mismatch")
    finally:
        os.close(descriptor)
    return registration


@dataclass(frozen=True)
class StorageAdmission:
    directory_fd: int
    snapshot: DevelopmentStorageSnapshot
    directory: Path
    _instance_fd: int
    _data_fd: int
    _image_fd: int

    def observe(self) -> DevelopmentStorageSnapshot:
        """Re-measure usage; whole backing bytes remain the single capacity charge."""
        name = PURPOSE_DIRECTORIES[self.snapshot.purpose]
        selected = os.fstat(self.directory_fd)
        current = os.stat(name, dir_fd=self._data_fd, follow_symlinks=False)
        if ((selected.st_dev, selected.st_ino) != (current.st_dev, current.st_ino)
                or selected.st_uid != UID or selected.st_mode & 0o077
                or os.readlink(f"/proc/self/fd/{self.directory_fd}") != str(self.directory)):
            raise DevelopmentStorageError("storage_purpose_path_replaced")
        return observe_storage(self._instance_fd, self._data_fd, self._image_fd,
                               self.snapshot.registration, self.snapshot.purpose)


def observe_storage(instance: int, data: int, image: int,
                    registration: DevelopmentStorageRegistration, purpose: StoragePurpose):
    backing = os.fstat(image)
    if (backing.st_dev, backing.st_ino, backing.st_size) != (
            registration.backing_device, registration.backing_inode, registration.backing_file_bytes):
        raise DevelopmentStorageError("storage_backing_replaced")
    identity = mounted_identity(data, registration.storage_id)
    current = os.stat("data", dir_fd=instance, follow_symlinks=False)
    opened = os.fstat(data)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise DevelopmentStorageError("storage_directory_replaced")
    values = os.fstatvfs(data)
    capacity, free, available = (value * values.f_frsize for value in (
        values.f_blocks, values.f_bfree, values.f_bavail))
    if capacity > registration.backing_file_bytes or values.f_flag & os.ST_RDONLY:
        raise DevelopmentStorageError("storage_filesystem_capacity_or_access_invalid")
    safety = registration.admission_safety_bytes
    return DevelopmentStorageSnapshot(registration=registration, observed_at=datetime.now(timezone.utc),
        purpose=purpose, **identity, backing_allocated_bytes=backing.st_blocks * 512,
        accounted_backing_bytes=registration.backing_file_bytes, filesystem_capacity_bytes=capacity,
        filesystem_free_bytes=free, filesystem_available_bytes=available,
        retained_bytes_including_metadata=capacity - free, admission_safety_bytes=safety,
        allocatable_bytes=max(0, available - safety))


class DevelopmentStorage:
    """Trusted host writers share a fixed pool and lock, not a per-call quota.

    Resolve references only from trusted installation records. Keep admission open
    for every writer and stop those writers before exiting it. Returned paths are
    valid only in that context; sandboxes must never receive the instance metadata.
    Workspace and candidate purposes deliberately share one root and lock.
    The requested bytes gate free headroom; the filesystem enforces the whole
    instance cap. Retained usage is a submeasurement, not a second capacity charge.
    """

    def __init__(self, storage_id: str) -> None:
        validate_id(storage_id)
        self.storage_id = storage_id

    def bind(self, purpose: StoragePurpose) -> DevelopmentStorageRef:
        """Pin the current real instance during trusted installation/maintenance."""
        with instance_descriptors(self.storage_id) as (_, instance):
            registration = registration_at(instance, self.storage_id)
        with self.admit(expected_instance_revision=registration.instance_revision,
                        requested_bytes=0, purpose=purpose):
            return DevelopmentStorageRef(storage_id=self.storage_id,
                instance_revision=registration.instance_revision, purpose=purpose)

    @contextmanager
    def admit_ref(self, reference: DevelopmentStorageRef, *, requested_bytes: int):
        if not isinstance(reference, DevelopmentStorageRef) or reference.storage_id != self.storage_id:
            raise DevelopmentStorageError("storage_reference_identity_mismatch")
        with self.admit(expected_instance_revision=reference.instance_revision,
                        requested_bytes=requested_bytes, purpose=reference.purpose) as admission:
            yield admission

    @contextmanager
    def admit(self, *, expected_instance_revision: str, requested_bytes: int, purpose: StoragePurpose):
        if (os.getuid() != UID or type(requested_bytes) is not int or requested_bytes < 0
                or purpose not in PURPOSE_DIRECTORIES):
            raise DevelopmentStorageError("storage_admission_request_invalid")
        with instance_descriptors(self.storage_id) as (_, instance), instance_lock(instance):
            registration = registration_at(instance, self.storage_id)
            if registration.instance_revision != expected_instance_revision:
                raise DevelopmentStorageError("storage_instance_revision_stale")
            if purpose not in registration.allowed_purposes:
                raise DevelopmentStorageError("storage_purpose_not_registered")
            data = directory_at(instance, "data")
            image, selected = None, None
            try:
                image = regular_at(instance, "volume.ext4")
                snapshot = observe_storage(instance, data, image, registration, purpose)
                if requested_bytes > snapshot.allocatable_bytes:
                    raise DevelopmentStorageError("storage_capacity_unavailable")
                name = PURPOSE_DIRECTORIES[purpose]
                selected = directory_at(data, name)
                if os.fstat(selected).st_dev != os.fstat(data).st_dev:
                    raise DevelopmentStorageError("storage_purpose_mount_boundary_mismatch")
                path = ROOT / self.storage_id / "data" / name
                if os.readlink(f"/proc/self/fd/{selected}") != str(path):
                    raise DevelopmentStorageError("storage_purpose_path_replaced")
                admission = StorageAdmission(selected, snapshot, path, instance, data, image)
                yield admission
                admission.observe()
            finally:
                if selected is not None:
                    os.close(selected)
                if image is not None:
                    os.close(image)
                os.close(data)
