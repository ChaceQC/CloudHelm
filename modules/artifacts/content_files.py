"""Linux private-root and inode-pinned I/O for immutable artifact archives."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from typing import BinaryIO, Iterator

from modules.artifacts.errors import ArtifactContentError


def file_shape(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _trusted(info, *, directory: bool, device=None, readonly=False, private=False):
    kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ArtifactContentError("artifact_storage_not_service_owned")
    if device is not None and info.st_dev != device:
        raise ArtifactContentError("artifact_storage_mount_boundary")
    if not directory and info.st_nlink != 1:
        raise ArtifactContentError("artifact_storage_hardlink_forbidden")
    if private and info.st_mode & 0o077:
        raise ArtifactContentError("artifact_directory_must_be_private")
    if readonly and info.st_mode & 0o222:
        raise ArtifactContentError("artifact_published_content_writable")


def _absolute_parts(path) -> list[str]:
    raw = os.fspath(path)
    if (not isinstance(raw, str) or not raw.startswith("/") or len(raw.encode("utf-8")) > 4096
            or any(part in {"", ".", ".."} for part in raw.split("/")[1:])
            or "\0" in raw or "\\" in raw):
        raise ArtifactContentError("artifact_trusted_path_invalid")
    return raw.split("/")[1:]


def _directory(path) -> int:
    if sys.platform != "linux":
        raise ArtifactContentError("artifact_linux_storage_required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for part in _absolute_parts(path):
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _trusted(os.fstat(descriptor), directory=True, private=True)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def directory_at(parent: int, name: str, *, readonly=False) -> Iterator[int]:
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
    try:
        _trusted(os.fstat(descriptor), directory=True, device=os.fstat(parent).st_dev,
                 readonly=readonly, private=True)
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def regular_at(parent: int, name: str, limit: int, *, readonly=False) -> Iterator[BinaryIO]:
    """Never open a special inode for I/O, including a pathname race to a FIFO."""
    pinned = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    descriptor = -1
    try:
        before = os.fstat(pinned)
        _trusted(before, directory=False, device=os.fstat(parent).st_dev, readonly=readonly)
        if before.st_size > limit:
            raise ArtifactContentError("artifact_archive_too_large")
        descriptor = os.open(f"/proc/self/fd/{pinned}", os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
            if file_shape(before) != file_shape(os.fstat(stream.fileno())):
                raise ArtifactContentError("artifact_content_changed")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(pinned)


@contextmanager
def source_archive(path, limit: int) -> Iterator[BinaryIO]:
    parts = _absolute_parts(path)
    if len(parts) < 2:
        raise ArtifactContentError("artifact_source_must_be_private")
    parent = _directory("/" + "/".join(parts[:-1]))
    try:
        with regular_at(parent, parts[-1], limit) as stream:
            yield stream
    finally:
        os.close(parent)


@contextmanager
def new_file(parent: int, name: str):
    descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
    with os.fdopen(descriptor, "w+b") as stream:
        yield stream
        stream.flush()
        os.fchmod(stream.fileno(), 0o400)
        os.fsync(stream.fileno())


def publish_directory(root: int, staging: str, storage_id: str) -> None:
    """Linux RENAME_NOREPLACE refuses every existing destination atomically."""
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise ArtifactContentError("artifact_atomic_publish_unsupported")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(root, staging.encode("ascii"), root, storage_id.encode("ascii"), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ArtifactContentError("artifact_publication_conflict")
        if code in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise ArtifactContentError("artifact_atomic_publish_unsupported")
        raise ArtifactContentError("artifact_publication_unconfirmed")
    os.fsync(root)


def remove_staging(root: int, name: str) -> None:
    """Only the caller-created two-file temporary directory is removable."""
    if not name.startswith("stage-") or not name[6:].isalnum():
        raise ArtifactContentError("artifact_cleanup_scope_invalid")
    with directory_at(root, name) as staging:
        os.fchmod(staging, 0o700)
        names = os.listdir(staging)
        if set(names) - {"archive.oci.tar", "receipt.json"}:
            raise ArtifactContentError("artifact_cleanup_scope_invalid")
        for entry in names:
            os.unlink(entry, dir_fd=staging)
    os.rmdir(name, dir_fd=root)


class ArtifactRoot:
    def __init__(self, path):
        self.fd = _directory(path)

    @contextmanager
    def exclusive(self):
        if self.fd < 0:
            raise ArtifactContentError("artifact_store_closed")
        descriptor = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=self.fd)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield descriptor
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
