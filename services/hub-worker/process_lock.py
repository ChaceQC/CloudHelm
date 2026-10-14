"""One worker per installation on this controlled Linux runtime account."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

_LOCK_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/worker-locks")
_PROCESS_LOCK_FDS: list[int] = []


class WorkerProcessLockError(RuntimeError):
    """Fixed startup category; no lock stealing or process killing is performed."""


def acquire_worker_process_lock(installation_id: str) -> None:
    """Keep the descriptor open until OS process exit, including during SDK drain."""
    if os.name != "posix":
        raise WorkerProcessLockError("worker_requires_controlled_linux_runtime")
    if not isinstance(installation_id, str) or not 1 <= len(installation_id) <= 160:
        raise WorkerProcessLockError("worker_installation_identity_invalid")
    import fcntl

    descriptor: int | None = None
    try:
        _LOCK_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_state = _LOCK_ROOT.stat()
        if _LOCK_ROOT.is_symlink() or root_state.st_uid != os.getuid() or root_state.st_mode & 0o077:
            raise WorkerProcessLockError("worker_lock_directory_not_private")
        name = hashlib.sha256(installation_id.encode("utf-8")).hexdigest() + ".lock"
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(_LOCK_ROOT / name, flags, 0o600)
        file_state = os.fstat(descriptor)
        if (not stat.S_ISREG(file_state.st_mode) or file_state.st_uid != os.getuid()
                or file_state.st_mode & 0o077):
            raise WorkerProcessLockError("worker_lock_file_not_private")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkerProcessLockError("worker_already_running") from None
        # Deliberately no finally-unlock/atexit-unlock: DBOS may still have live
        # executor threads after destroy() returns. Only process exit releases it.
        _PROCESS_LOCK_FDS.append(descriptor)
        descriptor = None
    except OSError:
        raise WorkerProcessLockError("worker_process_lock_unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
