"""Shared observation and cleanup for the fixed rootless BuildKit containers."""

from __future__ import annotations

import json
import os
import resource
import stat
import subprocess
import time
from pathlib import Path

from modules.execution.docker_endpoint import socket_path
from packages.contracts.p1.runner_contracts import CapabilityEvidence

from .toolchain import DOCKER, DockerClient, ProbeFailure, classify_diagnostic, safe_diagnostic

SOCKET = "unix:///run/user/1000/buildkit/buildkitd.sock"
CPU_QUOTA, CPU_PERIOD = 300000, 100000
MEMORY_BYTES, PIDS_LIMIT = 4 * 1024**3, 256
STATE_BYTES, OUTPUT_BYTES = 2560 * 1024**2, 256 * 1024**2
TEMP_BYTES, SHM_BYTES = 16 * 1024**2, 1024**2
INSTALL_CACHE_BYTES, INSTALL_TEMP_BYTES = 256 * 1024**2, 64 * 1024**2


def process_identity(pid: int) -> str | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return value.rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


class BuildKitContainer:
    capture_memory_peak = False

    def __init__(self, client: DockerClient, operation_id: str, directory: Path,
                 image: str, started: float) -> None:
        self.client, self.operation_id, self.directory = client, operation_id, directory
        self.image, self.started = image, started
        self.container_id: str | None = None
        self.cgroup: Path | None = None
        self.processes: dict[int, str | None] = {}

    def execute(self, *arguments: str, ceiling: int = 20, required: bool = True):
        return self.client.run("exec", "--user=1000:1000", self.container_id, *arguments,
                               timeout=self.remaining(ceiling), required=required)

    def _wait_for_worker(self) -> None:
        for _ in range(25):
            result = self.execute("buildctl", "--addr", SOCKET, "debug", "workers", "--verbose", required=False)
            if result.returncode == 0:
                labels = {}
                for line in result.stdout.splitlines():
                    key, separator, value = line.partition(":")
                    if separator:
                        labels[key.strip()] = value.strip()
                native = labels.get("org.mobyproject.buildkit.worker.snapshotter") == "native"
                sandbox = labels.get("org.mobyproject.buildkit.worker.oci.process-mode") == "sandbox"
                if not native or not sandbox:
                    raise ProbeFailure("probe_worker_snapshotter_or_process_sandbox_mismatch")
                return
            if not self.metadata()["State"]["Running"]:
                logs = self.client.run("logs", "--tail=30", self.container_id, required=False)
                raise ProbeFailure("probe_rootless_worker_start_failed",
                                   classify_diagnostic(logs.stdout + logs.stderr),
                                   safe_diagnostic(logs.stdout + logs.stderr))
            time.sleep(0.2)
        raise ProbeFailure("probe_worker_readiness_unconfirmed")

    def _observe_processes(self) -> list[tuple[int, str, list[bytes]]]:
        observed = []
        result = self.client.run("top", self.container_id, "-eo", "pid", timeout=self.remaining())
        for line in result.stdout.splitlines()[1:]:
            fields = line.split()
            if len(fields) != 1 or not fields[0].isdigit():
                raise ProbeFailure("probe_process_observation_invalid")
            pid = int(fields[0])
            identity = process_identity(pid)
            if identity is None:
                continue
            try:
                group = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").strip()
                command_line = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            except FileNotFoundError:
                continue
            expected = "/" + str(self.cgroup.relative_to("/sys/fs/cgroup"))
            if not any(line == f"0::{expected}" or line.startswith(f"0::{expected}/")
                       for line in group.splitlines()):
                raise ProbeFailure("probe_child_outside_parent_cgroup")
            self.processes[pid] = identity
            observed.append((pid, identity, command_line))
        return observed

    def stop_and_remove(self) -> CapabilityEvidence:
        if self.capture_memory_peak and self.cgroup is not None and self.cgroup.exists():
            self.memory_peak = int((self.cgroup / "memory.peak").read_text(encoding="utf-8"))
        if self.container_id is None:
            return CapabilityEvidence(capability="stop_confirmation", status="unverified", reason="not_started")
        metadata = self.metadata()
        if metadata["State"]["Running"]:
            self.client.run("stop", "--time=3", self.container_id, timeout=15)
        stopped = self.metadata()
        remaining = [pid for pid, identity in self.processes.items() if process_identity(pid) == identity]
        populated = False
        if self.cgroup is not None and self.cgroup.exists():
            populated = "populated 1" in (self.cgroup / "cgroup.events").read_text(encoding="utf-8")
        verified = not stopped["State"]["Running"] and stopped["State"]["Pid"] == 0 and not remaining and not populated
        if not verified:
            raise ProbeFailure("probe_stop_unconfirmed_reconciliation_required")
        self.client.run("rm", "--volumes", self.container_id, timeout=15)
        exists = self.client.run("ps", "--all", "--quiet", "--filter",
                                 f"label=cloudhelm.operation_id={self.operation_id}")
        if exists.stdout.strip():
            raise ProbeFailure("probe_owned_container_cleanup_unconfirmed")
        if self.cgroup is None:
            return CapabilityEvidence(capability="stop_confirmation", status="unverified",
                reason="host_process_group_not_observed", observations=(
                    "docker_running=false", "docker_pid=0", "owned_container_removed=true"))
        return CapabilityEvidence(capability="stop_confirmation", status="verified",
            reason="docker_and_host_process_stop_confirmed", observations=(
                f"tracked_processes={len(self.processes)}", "remaining_processes=0",
                "cgroup_populated=false", "owned_container_removed=true"))


class OfflineBuildKitContainer(BuildKitContainer):
    """Shared fixed offline build envelope and bounded OCI collection."""

    capture_memory_peak = True

    def _create_builder(self, *, scope: str, method: str, binds: dict[str, str],
                        tmpfs: dict[str, tuple[int, str]], cpu_quota: int, cpu_period: int,
                        memory: int, pids: int, shm: int, error_prefix: str) -> None:
        args = ["create", "--name", "cloudhelm-p1-" + self.operation_id,
            "--label", f"cloudhelm.scope={scope}", "--label", f"cloudhelm.method={method}",
            "--label", f"cloudhelm.operation_id={self.operation_id}", "--pull=never",
            "--platform=linux/amd64", "--network=none", "--user=1000:1000", "--read-only",
            "--ipc=private", f"--shm-size={shm}", "--env=TMPDIR=/tmp",
            f"--memory={memory}", f"--memory-swap={memory}",
            f"--cpu-period={cpu_period}", f"--cpu-quota={cpu_quota}", f"--pids-limit={pids}",
            "--log-driver=local", "--log-opt=max-size=1m", "--log-opt=max-file=1", "--log-opt=compress=false",
            "--security-opt=seccomp=unconfined", "--security-opt=systempaths=unconfined"]
        for destination, source in binds.items():
            args += ["--mount", f"type=bind,src={source},dst={destination},readonly,bind-propagation=rprivate"]
        for path, (size, mode) in tmpfs.items():
            args += ["--tmpfs", f"{path}:rw,nosuid,nodev,exec,uid=1000,gid=1000,mode={mode},size={size}"]
        args += ["--entrypoint=rootlesskit", self.image, "--state-dir=/run/user/1000/rootlesskit",
                 "buildkitd", "--rootless", "--addr=" + SOCKET,
                 "--oci-worker-snapshotter=native", "--containerd-worker=false"]
        self.container_id = self.client.run(*args, timeout=self.remaining()).stdout.strip()
        if len(self.container_id) != 64:
            raise ProbeFailure(error_prefix + "_container_identity_unavailable")
        self.client.run("start", self.container_id, timeout=self.remaining())
        self._wait_for_worker()

    def _observe_builder(self, *, tmpfs: dict[str, tuple[int, str]], cpu_quota: int, cpu_period: int,
                         memory: int, pids: int, shm: int, error_prefix: str,
                         verify_input_mounts: bool = False) -> tuple[dict, dict]:
        metadata = self.metadata()
        host, mounts = metadata["HostConfig"], metadata["Mounts"]
        binds = {item["Destination"]: item["Source"] for item in mounts if item["Type"] == "bind" and not item["RW"]}
        expected_tmpfs = {path: size for path, (size, _) in tmpfs.items()} | {"/dev/shm": shm}
        if (binds != self._binds() or sum(item["Type"] == "bind" for item in mounts) != len(binds)
                or any(item["Type"] not in ("bind", "tmpfs")
                       or item["Destination"] not in set(binds) | set(expected_tmpfs) for item in mounts)
                or metadata["Config"]["User"] != "1000:1000"
                or not host["ReadonlyRootfs"] or host["Privileged"] or host.get("Devices") or host.get("CapAdd")
                or host["NetworkMode"] != "none" or host["IpcMode"] != "private"
                or set(host["Tmpfs"]) != set(expected_tmpfs) - {"/dev/shm"}):
            raise ProbeFailure(error_prefix + "_container_boundary_mismatch")
        for destination, descriptor in (self.input_mounts if verify_input_mounts else {}).items():
            observed = self.execute("stat", "-c", "%d %i", destination).stdout.split()
            pinned = os.fstat(descriptor)
            if observed != [str(pinned.st_dev), str(pinned.st_ino)]:
                raise ProbeFailure(error_prefix + "_input_mount_identity_mismatch")
        groups = Path(f'/proc/{metadata["State"]["Pid"]}/cgroup').read_text(encoding="utf-8").splitlines()
        unified = next((line[3:] for line in groups if line.startswith("0::/")), None)
        if unified is None:
            raise ProbeFailure(error_prefix + "_unified_cgroup_unavailable")
        self.cgroup = Path("/sys/fs/cgroup") / unified.lstrip("/")
        if not self.cgroup.resolve().is_relative_to(Path("/sys/fs/cgroup")):
            raise ProbeFailure(error_prefix + "_cgroup_path_invalid")
        expected = {"cpu.max": f"{cpu_quota} {cpu_period}", "memory.max": str(memory),
                    "memory.swap.max": "0", "pids.max": str(pids)}
        observed = {name: (self.cgroup / name).read_text(encoding="utf-8").strip() for name in expected}
        if observed != expected:
            raise ProbeFailure(error_prefix + "_cgroup_limits_mismatch")
        storage = {}
        for path, size in expected_tmpfs.items():
            values = self.execute("stat", "-f", "-c", "%S %b", path).stdout.split()
            storage[path] = int(values[0]) * int(values[1])
            if storage[path] != size:
                raise ProbeFailure(error_prefix + "_tmpfs_capacity_mismatch")
        self._observe_processes()
        return observed, storage

    def _collect_archive(self, target: Path) -> None:
        def limit_file():
            resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_BYTES, OUTPUT_BYTES))

        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "DOCKER_CONFIG": str(self.client.config_directory)}
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                result = subprocess.run([DOCKER, "--host", "unix://" + socket_path(),
                    "exec", "--user=1000:1000", self.container_id, "cat", "/probe/output/image.oci.tar"],
                    env=environment, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE,
                    preexec_fn=limit_file, timeout=self.remaining(30), check=False)
                stream.flush()
                os.fsync(stream.fileno())
        except subprocess.TimeoutExpired:
            raise ProbeFailure("offline_archive_collection_timeout") from None
        if result.returncode:
            raise ProbeFailure("offline_archive_collection_failed", detail=safe_diagnostic(
                result.stderr.decode("utf-8", errors="replace")))


class ProductBuildBoundary(OfflineBuildKitContainer):
    """The fixed product build envelope; subclasses supply source mounts and identity."""

    def __init__(self, client, operation_id, directory, image, started, seed: Path) -> None:
        super().__init__(client, operation_id, directory, image, started)
        self.seed = seed
        self.input_mounts: dict[str, int] | None = None

    def remaining(self, ceiling: int = 20) -> float:
        remaining = self.wall_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ProbeFailure(self.error_prefix + "_execution_deadline_exceeded")
        return min(ceiling, remaining)

    def metadata(self) -> dict:
        metadata = json.loads(self.client.run("inspect", self.container_id, timeout=10).stdout)[0]
        labels = metadata["Config"].get("Labels") or {}
        if (labels.get("cloudhelm.scope") != self.scope or labels.get("cloudhelm.operation_id") != self.operation_id
                or labels.get("cloudhelm.method") != self.method):
            raise ProbeFailure(self.error_prefix + "_container_ownership_mismatch")
        return metadata

    def _binds(self) -> dict[str, str]:
        if self.input_mounts is None:
            opened = {}
            try:
                for destination, path in self._sources().items():
                    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    opened[destination] = descriptor
                    state = os.fstat(descriptor)
                    if (not stat.S_ISDIR(state.st_mode) or state.st_uid != os.getuid()
                            or state.st_mode & 0o222):
                        raise ProbeFailure(self.error_prefix + "_input_mount_not_readonly_owned")
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
                raise ProbeFailure(self.error_prefix + "_input_mount_identity_changed")
            paths[destination] = path
        return paths

    def stop_and_remove(self):
        stopped = super().stop_and_remove()
        if stopped.status == "verified":
            for descriptor in (self.input_mounts or {}).values():
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
            raise ProbeFailure(self.error_prefix + "_previous_execution_requires_reconciliation")
        self._create_builder(scope=self.scope, method=self.method, binds=self._binds(), tmpfs=self._tmpfs(),
            cpu_quota=CPU_QUOTA, cpu_period=CPU_PERIOD, memory=MEMORY_BYTES, pids=PIDS_LIMIT,
            shm=SHM_BYTES, error_prefix=self.error_prefix)

    def observe_boundary(self) -> dict:
        observed, storage = self._observe_builder(tmpfs=self._tmpfs(), cpu_quota=CPU_QUOTA,
            cpu_period=CPU_PERIOD, memory=MEMORY_BYTES, pids=PIDS_LIMIT, shm=SHM_BYTES,
            error_prefix=self.error_prefix, verify_input_mounts=True)
        return {"kernel_limits": observed, "outer_tmpfs_bytes": storage,
            "outer_tmpfs_capacity_sum": sum(storage.values()),
            "install_tmpfs_bytes": {"/private-cache": INSTALL_CACHE_BYTES, "/tmp": INSTALL_TEMP_BYTES},
            "network": "none", "readonly_root": True, "source_binds_readonly": True,
            "process_sandbox": True, "snapshotter": "native", "execution_wall_seconds": self.wall_seconds,
            "security_exceptions": ["seccomp=unconfined", "systempaths=unconfined"]}
