"""Exclusive credential delivery on Linux filesystems with enforced POSIX modes."""

import os
from pathlib import Path
import re
import stat
import sys

from pydantic import SecretStr

from modules.identity.authentication import _token_digest

_NATIVE_FILESYSTEMS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "tmpfs", "overlay"}


class CredentialFileError(ValueError):
    """Fixed category only; no credential contents or operating-system diagnostics."""


def validate_destination(value: str) -> Path:
    if sys.platform != "linux":
        raise CredentialFileError("credential_linux_required")
    if (not isinstance(value, str) or not 1 <= len(value) <= 4096
            or any(character in value for character in "\x00\r\n") or value.startswith("//")):
        raise CredentialFileError("credential_path_invalid")
    path = Path(value)
    if not path.is_absolute() or path.name in {"", ".", ".."} or ".." in path.parts or len(path.parts) > 64:
        raise CredentialFileError("credential_path_invalid")
    return path


def _unescape_mount(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _require_native(directory_fd: int) -> None:
    actual = os.readlink(f"/proc/self/fd/{directory_fd}")
    if not actual.startswith("/") or actual.endswith(" (deleted)"):
        raise CredentialFileError("credential_directory_invalid")
    matches = []
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        left, right = line.split(" - ", 1)
        mount = _unescape_mount(left.split()[4])
        if mount == "/" or actual == mount or actual.startswith(mount.rstrip("/") + "/"):
            matches.append((len(mount), right.split()[0]))
    if not matches or max(matches)[1] not in _NATIVE_FILESYSTEMS:
        raise CredentialFileError("credential_native_filesystem_required")


def _open_private_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                _require_native(descriptor)
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise CredentialFileError("credential_directory_permissions_invalid")
        _require_native(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def write_credential_file(destination: str, bearer: SecretStr) -> str:
    """Never overwrite. A delivered file is retained if later DB commit is uncertain."""
    path = validate_destination(destination)
    _token_digest(bearer)
    directory_fd = None
    descriptor = None
    try:
        directory_fd = _open_private_directory(path.parent)
        descriptor = os.open(
            path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise CredentialFileError("credential_file_invalid")
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            stream.write(bearer.get_secret_value() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory_fd)
        return str(path)
    except FileExistsError:
        raise CredentialFileError("credential_file_exists") from None
    except (OSError, UnicodeError, IndexError):
        raise CredentialFileError("credential_file_write_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)
