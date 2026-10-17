"""Kernel identities for the supported trusted writer and read-only readers."""

from pathlib import PurePosixPath

from modules.workspaces.safe_paths import WorkspaceFileError


def process_start_ticks(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
            return int(stream.read(8192).rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        raise WorkspaceFileError("workspace_writer_identity_unavailable") from None


def overlaps(left, right):
    left, right = PurePosixPath(left), PurePosixPath(right)
    return left == right or left in right.parents or right in left.parents


def _read(path, limit):
    with open(path, encoding="utf-8") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise WorkspaceFileError("workspace_writer_scan_limit_exceeded")
    return value


def verify_kernel_reader(pid, destination):
    try:
        records = _read(f"/proc/{pid}/mountinfo", 2 * 1024 * 1024).splitlines()
        matches = [line.split() for line in records if line.split()[4] == destination]
        if len(matches) != 1 or "ro" not in matches[0][5].split(","):
            raise WorkspaceFileError("workspace_reader_mount_unconfirmed")
    except (OSError, IndexError):
        raise WorkspaceFileError("workspace_reader_mount_unconfirmed") from None
