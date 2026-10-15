"""One fixed, offline, bounded maintenance probe on the registered WSL runtime."""

from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path

from .toolchain import ProbeFailure, RUNTIME_ROOT, private_directory

METHOD = "p1-runner-capabilities-r1"
SCOPE_LABEL = "cloudhelm.scope=p1-runner-probe"
MEMORY_BYTES = 512 * 1024 * 1024
PIDS_LIMIT = 128
CPU_QUOTA = 100000
CPU_PERIOD = 100000
STATE_BYTES = 64 * 1024 * 1024
TMP_BYTES = 8 * 1024 * 1024
SHM_BYTES = 1024 * 1024
WALL_SECONDS = 90
SECURITY_EXCEPTIONS = ("seccomp=unconfined", "systempaths=unconfined")
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


def container_name(operation_id: str) -> str:
    if not re.fullmatch(r"runner-probe-[a-f0-9]{32}", operation_id):
        raise ProbeFailure("probe_operation_identity_invalid")
    return "cloudhelm-p1-" + operation_id


def container_arguments(operation_id: str, image: str, context: Path) -> list[str]:
    expected = RUNTIME_ROOT / operation_id / "context"
    if context != expected or context.is_symlink() or not context.is_dir():
        raise ProbeFailure("probe_context_not_registered")
    args = ["create", "--name", container_name(operation_id), "--label", SCOPE_LABEL,
            "--label", f"cloudhelm.operation_id={operation_id}",
            "--label", f"cloudhelm.method={METHOD}", "--pull=never",
            "--platform=linux/amd64", "--network=none", "--user=1000:1000", "--read-only",
            "--ipc=private", f"--shm-size={SHM_BYTES}",
            "--env=TMPDIR=/tmp",
            f"--memory={MEMORY_BYTES}", f"--memory-swap={MEMORY_BYTES}",
            f"--cpu-period={CPU_PERIOD}", f"--cpu-quota={CPU_QUOTA}", f"--pids-limit={PIDS_LIMIT}",
            "--log-driver=local", "--log-opt=max-size=1m", "--log-opt=max-file=1", "--log-opt=compress=false",
            "--mount", f"type=bind,src={context},dst=/probe/input,readonly,bind-propagation=rprivate"]
    for exception in SECURITY_EXCEPTIONS:
        args += ["--security-opt", exception]
    for path, size, mode in (("/home/user/.local/share/buildkit", STATE_BYTES, "0700"),
                              ("/run/user/1000", TMP_BYTES, "0700"),
                              ("/tmp", TMP_BYTES, "1777")):
        args += ["--tmpfs", f"{path}:rw,nosuid,nodev,exec,uid=1000,gid=1000,mode={mode},size={size}"]
    return args + ["--entrypoint=rootlesskit", image, "--state-dir=/run/user/1000/rootlesskit",
                   "buildkitd", "--rootless",
                   "--addr=unix:///run/user/1000/buildkit/buildkitd.sock",
                   "--oci-worker-snapshotter=native", "--containerd-worker=false"]


def ensure_owned(metadata: dict, operation_id: str) -> None:
    labels = metadata.get("Config", {}).get("Labels") or {}
    if (labels.get("cloudhelm.scope") != "p1-runner-probe"
            or labels.get("cloudhelm.operation_id") != operation_id
            or labels.get("cloudhelm.method") != METHOD):
        raise ProbeFailure("probe_container_ownership_mismatch")
