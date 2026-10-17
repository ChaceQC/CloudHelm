"""One fixed backend builder envelope, checked against Linux kernel facts."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from .offline_image_runtime import OfflineImageRuntime, SOCKET
from .toolchain import ProbeFailure

METHOD = "p1-backend-offline-build-r1"
SCOPE = "p1-backend-offline-build"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/backend-build-check")
CPU_QUOTA, CPU_PERIOD = 300000, 100000
MEMORY_BYTES, PIDS_LIMIT = 4 * 1024**3, 256
STATE_BYTES, OUTPUT_BYTES = 2560 * 1024**2, 256 * 1024**2
TEMP_BYTES, SHM_BYTES = 16 * 1024**2, 1024**2
INSTALL_CACHE_BYTES, INSTALL_TEMP_BYTES = 256 * 1024**2, 64 * 1024**2
WALL_SECONDS = 420


class BackendBuildBoundary(OfflineImageRuntime):
    def __init__(self, client, operation_id, directory, image, started, seed: Path) -> None:
        super().__init__(client, operation_id, directory, image, started)
        self.seed = seed

    def remaining(self, ceiling: int = 20) -> float:
        remaining = WALL_SECONDS - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ProbeFailure("backend_execution_deadline_exceeded")
        return min(ceiling, remaining)

    def metadata(self) -> dict:
        metadata = json.loads(self.client.run("inspect", self.container_id, timeout=10).stdout)[0]
        labels = metadata["Config"].get("Labels") or {}
        if (labels.get("cloudhelm.scope") != SCOPE or labels.get("cloudhelm.operation_id") != self.operation_id
                or labels.get("cloudhelm.method") != METHOD):
            raise ProbeFailure("backend_container_ownership_mismatch")
        return metadata

    def _binds(self) -> dict[str, str]:
        if not hasattr(self, "input_mounts"):
            opened = {}
            sources = {"/probe/context": self.directory / "context",
                       "/probe/base": self.directory / "base-layout", "/probe/python-seed": self.seed}
            try:
                for destination, path in sources.items():
                    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    opened[destination] = descriptor
                    state = os.fstat(descriptor)
                    if (not stat.S_ISDIR(state.st_mode) or state.st_uid != os.getuid()
                            or state.st_mode & 0o222):
                        raise ProbeFailure("backend_input_mount_not_readonly_owned")
            except BaseException:
                for descriptor in opened.values():
                    os.close(descriptor)
                raise
            self.input_mounts = opened
        paths = {}
        for destination, descriptor in self.input_mounts.items():
            path = os.readlink(f"/proc/self/fd/{descriptor}")
            pinned, current = os.fstat(descriptor), os.stat(path, follow_symlinks=False)
            if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
                raise ProbeFailure("backend_input_mount_identity_changed")
            paths[destination] = path
        return paths

    def stop_and_remove(self):
        stopped = super().stop_and_remove()
        if stopped.status == "verified":
            for descriptor in getattr(self, "input_mounts", {}).values():
                os.close(descriptor)
            self.input_mounts = {}
        return stopped

    @staticmethod
    def _tmpfs() -> dict[str, tuple[int, str]]:
        return {"/home/user/.local/share/buildkit": (STATE_BYTES, "0700"),
                "/run/user/1000": (TEMP_BYTES, "0700"), "/tmp": (TEMP_BYTES, "1777"),
                "/probe/output": (OUTPUT_BYTES, "0700")}

    def create(self) -> None:
        existing = self.client.run("ps", "--all", "--quiet", "--filter", "label=cloudhelm.method")
        if existing.stdout.strip():
            raise ProbeFailure("backend_previous_execution_requires_reconciliation")
        args = ["create", "--name", "cloudhelm-p1-" + self.operation_id,
            "--label", f"cloudhelm.scope={SCOPE}", "--label", f"cloudhelm.method={METHOD}",
            "--label", f"cloudhelm.operation_id={self.operation_id}", "--pull=never",
            "--platform=linux/amd64", "--network=none", "--user=1000:1000", "--read-only",
            "--ipc=private", f"--shm-size={SHM_BYTES}", "--env=TMPDIR=/tmp",
            f"--memory={MEMORY_BYTES}", f"--memory-swap={MEMORY_BYTES}",
            f"--cpu-period={CPU_PERIOD}", f"--cpu-quota={CPU_QUOTA}", f"--pids-limit={PIDS_LIMIT}",
            "--log-driver=local", "--log-opt=max-size=1m", "--log-opt=max-file=1", "--log-opt=compress=false",
            "--security-opt=seccomp=unconfined", "--security-opt=systempaths=unconfined"]
        for destination, source in self._binds().items():
            args += ["--mount", f"type=bind,src={source},dst={destination},readonly,bind-propagation=rprivate"]
        for path, (size, mode) in self._tmpfs().items():
            args += ["--tmpfs", f"{path}:rw,nosuid,nodev,exec,uid=1000,gid=1000,mode={mode},size={size}"]
        args += ["--entrypoint=rootlesskit", self.image, "--state-dir=/run/user/1000/rootlesskit",
                 "buildkitd", "--rootless", "--addr=" + SOCKET,
                 "--oci-worker-snapshotter=native", "--containerd-worker=false"]
        self.container_id = self.client.run(*args, timeout=self.remaining()).stdout.strip()
        if len(self.container_id) != 64:
            raise ProbeFailure("backend_container_identity_unavailable")
        self.client.run("start", self.container_id, timeout=self.remaining())
        self._wait_for_worker()

    def observe_boundary(self) -> dict:
        metadata = self.metadata()
        host, mounts = metadata["HostConfig"], metadata["Mounts"]
        binds = {item["Destination"]: item["Source"] for item in mounts if item["Type"] == "bind" and not item["RW"]}
        expected_tmpfs = {path: size for path, (size, _) in self._tmpfs().items()} | {"/dev/shm": SHM_BYTES}
        if (binds != self._binds() or sum(item["Type"] == "bind" for item in mounts) != len(binds)
                or any(item["Type"] not in ("bind", "tmpfs")
                       or item["Destination"] not in set(binds) | set(expected_tmpfs) for item in mounts)
                or metadata["Config"]["User"] != "1000:1000"
                or not host["ReadonlyRootfs"] or host["Privileged"] or host.get("Devices") or host.get("CapAdd")
                or host["NetworkMode"] != "none" or host["IpcMode"] != "private"
                or set(host["Tmpfs"]) != set(expected_tmpfs) - {"/dev/shm"}):
            raise ProbeFailure("backend_container_boundary_mismatch")
        for destination, descriptor in self.input_mounts.items():
            observed = self.execute("stat", "-c", "%d %i", destination).stdout.split()
            pinned = os.fstat(descriptor)
            if observed != [str(pinned.st_dev), str(pinned.st_ino)]:
                raise ProbeFailure("backend_input_mount_identity_mismatch")
        groups = Path(f'/proc/{metadata["State"]["Pid"]}/cgroup').read_text(encoding="utf-8").splitlines()
        unified = next((line[3:] for line in groups if line.startswith("0::/")), None)
        if unified is None:
            raise ProbeFailure("backend_unified_cgroup_unavailable")
        self.cgroup = Path("/sys/fs/cgroup") / unified.lstrip("/")
        if not self.cgroup.resolve().is_relative_to(Path("/sys/fs/cgroup")):
            raise ProbeFailure("backend_cgroup_path_invalid")
        expected = {"cpu.max": f"{CPU_QUOTA} {CPU_PERIOD}", "memory.max": str(MEMORY_BYTES),
                    "memory.swap.max": "0", "pids.max": str(PIDS_LIMIT)}
        observed = {name: (self.cgroup / name).read_text(encoding="utf-8").strip() for name in expected}
        if observed != expected:
            raise ProbeFailure("backend_cgroup_limits_mismatch")
        storage = {}
        for path, size in expected_tmpfs.items():
            values = self.execute("stat", "-f", "-c", "%S %b", path).stdout.split()
            storage[path] = int(values[0]) * int(values[1])
            if storage[path] != size:
                raise ProbeFailure("backend_tmpfs_capacity_mismatch")
        self._observe_processes()
        return {"kernel_limits": observed, "outer_tmpfs_bytes": storage,
            "outer_tmpfs_capacity_sum": sum(storage.values()),
            "install_tmpfs_bytes": {"/private-cache": INSTALL_CACHE_BYTES, "/tmp": INSTALL_TEMP_BYTES},
            "network": "none", "readonly_root": True, "source_binds_readonly": True,
            "process_sandbox": True, "snapshotter": "native", "execution_wall_seconds": WALL_SECONDS,
            "security_exceptions": ["seccomp=unconfined", "systempaths=unconfined"]}
