"""Shared lock for the registered WSL storage maintenance probe."""

from __future__ import annotations

import fcntl
import os
import stat

from .toolchain import ProbeFailure, RUNTIME_ROOT, private_directory

_LOCK_DESCRIPTORS: list[int] = []


def acquire_probe_lock() -> None:
    if os.name != "posix" or os.getuid() != 1000:
        raise ProbeFailure("probe_requires_registered_wsl_uid_1000")
    private_directory(RUNTIME_ROOT)
    descriptor = os.open(RUNTIME_ROOT / "execution.lock",
                         os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    state = os.fstat(descriptor)
    if not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid() or state.st_mode & 0o077:
        os.close(descriptor)
        raise ProbeFailure("probe_execution_lock_not_private")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise ProbeFailure("probe_execution_group_busy") from None
    # OS exit releases this only after the caller's stop/reconciliation path.
    _LOCK_DESCRIPTORS.append(descriptor)
