"""One bounded rootless BuildKit run using a fixed read-only local OCI base."""

from __future__ import annotations

import json
import os
import resource
import subprocess
import time
from pathlib import Path

from .capabilities import CapabilityProbe
from .toolchain import DOCKER, ProbeFailure, safe_diagnostic

METHOD = "p1-offline-image-probe-r1"
SCOPE = "p1-offline-image-probe"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/offline-image-probe")
CPU_QUOTA, CPU_PERIOD = 200000, 100000
MEMORY_BYTES, PIDS_LIMIT = 2 * 1024**3, 256
STATE_BYTES, OUTPUT_BYTES = 768 * 1024**2, 256 * 1024**2
TEMP_BYTES, SHM_BYTES = 16 * 1024**2, 1024**2
WALL_SECONDS = 180
SOCKET = "unix:///run/user/1000/buildkit/buildkitd.sock"
VERSION_SENTINEL = "CLOUDHELM_OFFLINE_PYTHON=3.12.13"
DOCKERFILE = '''FROM pythonbase
RUN --network=none ["python", "-I", "-c", "import sys; assert sys.version_info[:3] == (3, 12, 13); print('CLOUDHELM_OFFLINE_PYTHON=3.12.13', flush=True)"]
'''


class OfflineImageRuntime(CapabilityProbe):
    """Reuse only observation/stop helpers; no old probe policy is mutated."""

    def remaining(self, ceiling: int = 20) -> float:
        remaining = WALL_SECONDS - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ProbeFailure("offline_execution_deadline_exceeded")
        return min(ceiling, remaining)

    def metadata(self) -> dict:
        metadata = json.loads(self.client.run("inspect", self.container_id, timeout=10).stdout)[0]
        labels = metadata["Config"].get("Labels") or {}
        if (labels.get("cloudhelm.scope") != SCOPE
                or labels.get("cloudhelm.operation_id") != self.operation_id
                or labels.get("cloudhelm.method") != METHOD):
            raise ProbeFailure("offline_container_ownership_mismatch")
        return metadata

    def create(self) -> None:
        for scope in (SCOPE, "p1-runner-probe"):
            existing = self.client.run("ps", "--all", "--quiet", "--filter", f"label=cloudhelm.scope={scope}")
            if existing.stdout.strip():
                raise ProbeFailure("offline_previous_execution_requires_reconciliation")
        context = self.directory / "context"
        context.mkdir(mode=0o700)
        descriptor = os.open(context / "Dockerfile", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(DOCKERFILE)
        args = ["create", "--name", "cloudhelm-p1-" + self.operation_id,
            "--label", f"cloudhelm.scope={SCOPE}", "--label", f"cloudhelm.method={METHOD}",
            "--label", f"cloudhelm.operation_id={self.operation_id}", "--pull=never",
            "--platform=linux/amd64", "--network=none", "--user=1000:1000", "--read-only",
            "--ipc=private", f"--shm-size={SHM_BYTES}", "--env=TMPDIR=/tmp",
            f"--memory={MEMORY_BYTES}", f"--memory-swap={MEMORY_BYTES}",
            f"--cpu-period={CPU_PERIOD}", f"--cpu-quota={CPU_QUOTA}", f"--pids-limit={PIDS_LIMIT}",
            "--log-driver=local", "--log-opt=max-size=1m", "--log-opt=max-file=1", "--log-opt=compress=false",
            "--security-opt=seccomp=unconfined", "--security-opt=systempaths=unconfined"]
        for source, destination in ((context, "/probe/context"), (self.directory / "base-layout", "/probe/base")):
            args += ["--mount", f"type=bind,src={source},dst={destination},readonly,bind-propagation=rprivate"]
        for path, size, mode in (("/home/user/.local/share/buildkit", STATE_BYTES, "0700"),
                                 ("/run/user/1000", TEMP_BYTES, "0700"), ("/tmp", TEMP_BYTES, "1777"),
                                 ("/probe/output", OUTPUT_BYTES, "0700")):
            args += ["--tmpfs", f"{path}:rw,nosuid,nodev,exec,uid=1000,gid=1000,mode={mode},size={size}"]
        args += ["--entrypoint=rootlesskit", self.image, "--state-dir=/run/user/1000/rootlesskit",
                 "buildkitd", "--rootless", "--addr=" + SOCKET,
                 "--oci-worker-snapshotter=native", "--containerd-worker=false"]
        self.container_id = self.client.run(*args, timeout=self.remaining()).stdout.strip()
        if len(self.container_id) != 64:
            raise ProbeFailure("offline_container_identity_unavailable")
        self.client.run("start", self.container_id, timeout=self.remaining())
        self._wait_for_worker()

    def observe_boundary(self) -> dict:
        metadata = self.metadata()
        host = metadata["HostConfig"]
        mounts = metadata["Mounts"]
        expected_binds = {"/probe/context": str(self.directory / "context"),
                          "/probe/base": str(self.directory / "base-layout")}
        binds = {item["Destination"]: item["Source"] for item in mounts if item["Type"] == "bind" and not item["RW"]}
        expected_tmpfs = {"/home/user/.local/share/buildkit": STATE_BYTES, "/run/user/1000": TEMP_BYTES,
                          "/tmp": TEMP_BYTES, "/probe/output": OUTPUT_BYTES, "/dev/shm": SHM_BYTES}
        if (binds != expected_binds or sum(item["Type"] == "bind" for item in mounts) != 2
                or any(item["Type"] not in ("bind", "tmpfs")
                       or item["Destination"] not in set(expected_binds) | set(expected_tmpfs) for item in mounts)
                or metadata["Config"]["User"] != "1000:1000"
                or not host["ReadonlyRootfs"] or host["Privileged"] or host.get("Devices") or host.get("CapAdd")
                or host["NetworkMode"] != "none" or host["IpcMode"] != "private"
                or set(host["Tmpfs"]) != set(expected_tmpfs) - {"/dev/shm"}):
            raise ProbeFailure("offline_container_boundary_mismatch")
        pid = metadata["State"]["Pid"]
        groups = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        unified = next((line[3:] for line in groups if line.startswith("0::/")), None)
        if unified is None:
            raise ProbeFailure("offline_unified_cgroup_unavailable")
        self.cgroup = Path("/sys/fs/cgroup") / unified.lstrip("/")
        if not self.cgroup.resolve().is_relative_to(Path("/sys/fs/cgroup")):
            raise ProbeFailure("offline_cgroup_path_invalid")
        expected_limits = {"cpu.max": f"{CPU_QUOTA} {CPU_PERIOD}", "memory.max": str(MEMORY_BYTES),
                           "memory.swap.max": "0", "pids.max": str(PIDS_LIMIT)}
        observed = {name: (self.cgroup / name).read_text(encoding="utf-8").strip() for name in expected_limits}
        if observed != expected_limits:
            raise ProbeFailure("offline_cgroup_limits_mismatch")
        storage = {}
        for path, expected in expected_tmpfs.items():
            values = self.execute("stat", "-f", "-c", "%S %b", path).stdout.split()
            storage[path] = int(values[0]) * int(values[1])
            if storage[path] != expected:
                raise ProbeFailure("offline_tmpfs_capacity_mismatch")
        self._observe_processes()
        return {"kernel_limits": observed, "tmpfs_bytes": storage,
                "tmpfs_capacity_sum": sum(storage.values()), "network": "none", "readonly_root": True,
                "process_sandbox": True, "snapshotter": "native", "source_binds_readonly": True,
                "execution_wall_seconds": WALL_SECONDS,
                "security_exceptions": ["seccomp=unconfined", "systempaths=unconfined"]}

    def export_image(self, manifest_digest: str) -> dict:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            build = executor.submit(self.execute, "buildctl", "--addr", SOCKET, "build",
                "--frontend=dockerfile.v0", "--local=context=/probe/context", "--local=dockerfile=/probe/context",
                "--oci-layout=python=/probe/base", "--opt=context:pythonbase=oci-layout://python@" + manifest_digest,
                "--opt=platform=linux/amd64", "--no-cache", "--progress=plain",
                "--output=type=oci,dest=/probe/output/image.oci.tar,oci-mediatypes=true,compression=gzip",
                "--metadata-file=/probe/output/build-metadata.json", ceiling=120)
            while not build.done():
                self._observe_processes()
                time.sleep(0.15)
            result = build.result()
        if VERSION_SENTINEL not in result.stdout + result.stderr:
            raise ProbeFailure("offline_python_version_command_not_observed")
        metadata = json.loads(self.execute("cat", "/probe/output/build-metadata.json").stdout)
        digest = self.execute("sha256sum", "/probe/output/image.oci.tar").stdout.split()[0]
        size = int(self.execute("stat", "-c", "%s", "/probe/output/image.oci.tar").stdout)
        if not 0 < size <= OUTPUT_BYTES:
            raise ProbeFailure("offline_output_archive_size_invalid")
        target = self.directory / "image.oci.tar"
        self._collect_archive(target)
        if target.stat().st_size != size:
            raise ProbeFailure("offline_collected_archive_size_mismatch")
        self._observe_processes()
        return {"archive_path": str(target), "archive_digest": "sha256:" + digest, "archive_bytes": size,
                "exporter_manifest_digest": metadata.get("containerimage.digest"),
                "exporter_config_digest": metadata.get("containerimage.config.digest"),
                "python_version": "3.12.13", "cache_policy": "no-cache"}

    def _collect_archive(self, target: Path) -> None:
        def limit_file():
            resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_BYTES, OUTPUT_BYTES))

        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "DOCKER_CONFIG": str(self.client.config_directory)}
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                result = subprocess.run([DOCKER, "--host", "unix:///var/run/docker.sock",
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

    def stopped_resources(self) -> dict:
        stopped = self.stop_and_remove()
        return {"confirmation": stopped.model_dump(mode="json"),
                "process_resources_released": stopped.status == "verified",
                "memory_peak_bytes": getattr(self, "memory_peak", None),
                "host_archive_bytes_are_retained": True}

    def stop_and_remove(self):
        if self.cgroup is not None and self.cgroup.exists():
            self.memory_peak = int((self.cgroup / "memory.peak").read_text(encoding="utf-8"))
        return super().stop_and_remove()
