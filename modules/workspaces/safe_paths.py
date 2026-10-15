"""Linux fd-relative storage operations under a service-owned private root."""

import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import PurePosixPath

from packages.contracts.p1.workspace_git import workspace_path


class WorkspaceFileError(ValueError):
    """Only the stable code may cross a diagnostic or HTTP boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
_PIN = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC


def _path(value: str) -> list[str]:
    try:
        return workspace_path(value).split("/")
    except (ValueError, UnicodeError):
        raise WorkspaceFileError("workspace_path_invalid") from None


def _trusted(info: os.stat_result, *, directory: bool, device: int | None = None) -> None:
    kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise WorkspaceFileError("storage_not_service_owned")
    if device is not None and info.st_dev != device:
        raise WorkspaceFileError("storage_mount_boundary")
    if not directory and info.st_nlink != 1:
        raise WorkspaceFileError("storage_hardlink_forbidden")


@contextmanager
def directory_at(parent_fd: int, path: str, *, create: bool = False):
    """For private metadata/staging, not an unfrozen untrusted live workspace."""
    current = os.dup(parent_fd)
    device = os.fstat(parent_fd).st_dev
    try:
        for part in _path(path):
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
            following = os.open(part, _DIRECTORY, dir_fd=current)
            os.close(current)
            current = following
            _trusted(os.fstat(current), directory=True, device=device)
        yield current
    except OSError:
        raise WorkspaceFileError("storage_path_unavailable") from None
    finally:
        os.close(current)


def exists_at(parent_fd: int, name: str) -> bool:
    if len(_path(name)) != 1:
        raise WorkspaceFileError("storage_name_invalid")
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def read_regular(parent_fd: int, name: str, limit: int) -> bytes:
    parts = _path(name)
    parent = "/".join(parts[:-1])
    if parent:
        with directory_at(parent_fd, parent) as directory:
            return read_regular(directory, parts[-1], limit)
    pinned, descriptor = -1, -1
    try:
        pinned = os.open(parts[-1], _PIN, dir_fd=parent_fd)
        before = os.fstat(pinned)
        _trusted(before, directory=False, device=os.fstat(parent_fd).st_dev)
        if before.st_size > limit:
            raise WorkspaceFileError("storage_file_too_large")
        # Reopen the verified inode, so special files are never opened for I/O
        # and replacing the original pathname cannot redirect this read.
        descriptor = os.open(f"/proc/self/fd/{pinned}", _READ)
        output = bytearray()
        while len(output) <= limit:
            block = os.read(descriptor, min(65536, limit + 1 - len(output)))
            if not block:
                break
            output.extend(block)
        after = os.fstat(descriptor)
        shape = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if len(output) > limit or shape(before) != shape(after) or len(output) != after.st_size:
            raise WorkspaceFileError("storage_file_changed")
        return bytes(output)
    except OSError:
        raise WorkspaceFileError("storage_file_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if pinned >= 0:
            os.close(pinned)


def write_new_file(parent_fd: int, path: str, data: bytes, *, executable: bool = False) -> None:
    parts = _path(path)
    if len(parts) > 1:
        with directory_at(parent_fd, "/".join(parts[:-1]), create=True) as parent:
            write_new_file(parent, parts[-1], data, executable=executable)
        return
    descriptor = -1
    try:
        descriptor = os.open(parts[0], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent_fd)
        _trusted(os.fstat(descriptor), directory=False, device=os.fstat(parent_fd).st_dev)
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise WorkspaceFileError("storage_write_failed")
            remaining = remaining[written:]
        os.fchmod(descriptor, 0o755 if executable else 0o644)
        os.fsync(descriptor)
        os.fsync(parent_fd)
    except OSError:
        raise WorkspaceFileError("storage_write_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def remove_staging(parent_fd: int, name: str) -> None:
    """Only caller-created, unpublished staging directories may be removed."""
    if not name.startswith("stage-") or "/" in name:
        raise WorkspaceFileError("storage_cleanup_scope_invalid")
    with directory_at(parent_fd, name) as staged:
        _remove_contents(staged)
    os.rmdir(name, dir_fd=parent_fd)


def _remove_contents(directory: int) -> None:
    for name in os.listdir(directory):
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with directory_at(directory, name) as child:
                _remove_contents(child)
            os.rmdir(name, dir_fd=directory)
        else:
            os.unlink(name, dir_fd=directory)


class PrivateRoot:
    def __init__(self, path: str | os.PathLike[str]):
        if sys.platform != "linux":
            raise WorkspaceFileError("linux_storage_required")
        raw = os.fspath(path)
        parsed = PurePosixPath(raw)
        if not parsed.is_absolute() or ".." in parsed.parts:
            raise WorkspaceFileError("storage_root_invalid")
        descriptor = os.open("/", _DIRECTORY)
        try:
            for part in parsed.parts[1:]:
                following = os.open(part, _DIRECTORY, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            info = os.fstat(descriptor)
            _trusted(info, directory=True)
            if info.st_mode & 0o077:
                raise WorkspaceFileError("storage_root_must_be_private")
        except (OSError, ValueError):
            os.close(descriptor)
            raise WorkspaceFileError("storage_root_unavailable") from None
        self.fd = descriptor

    @contextmanager
    def exclusive(self):
        if self.fd < 0:
            raise WorkspaceFileError("storage_root_closed")
        descriptor = os.open(".", _DIRECTORY, dir_fd=self.fd)
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
