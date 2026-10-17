"""Bounded offline reference dependency installation; no application execution."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .offline_image_runtime import OfflineImageRuntime, SOCKET
from .python_dependencies import (
    PythonDependencyInput, derived_project, reference_inputs, verify_derived_inputs, verify_seed,
)
from .toolchain import ProbeFailure, safe_diagnostic

METHOD = "p1-python-offline-dependencies-r1"
SCOPE = "p1-python-offline-dependencies"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/python-dependency-check")
CPU_QUOTA, CPU_PERIOD = 300000, 100000
MEMORY_BYTES, PIDS_LIMIT = 4 * 1024**3, 256
STATE_BYTES, OUTPUT_BYTES = 2 * 1024**3, 1024**2
TEMP_BYTES, SHM_BYTES = 16 * 1024**2, 1024**2
INSTALL_CACHE_BYTES, INSTALL_TEMP_BYTES = 256 * 1024**2, 64 * 1024**2
WALL_SECONDS = 240
ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "infra/p1/reference-build/backend.offline.Dockerfile"


class PythonDependencyRuntime(OfflineImageRuntime):
    def __init__(self, client, operation_id, directory, image, started, seed: Path) -> None:
        super().__init__(client, operation_id, directory, image, started)
        self.seed = seed

    def remaining(self, ceiling: int = 20) -> float:
        remaining = WALL_SECONDS - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ProbeFailure("python_dependency_execution_deadline_exceeded")
        return min(ceiling, remaining)

    def metadata(self) -> dict:
        metadata = json.loads(self.client.run("inspect", self.container_id, timeout=10).stdout)[0]
        labels = metadata["Config"].get("Labels") or {}
        if (labels.get("cloudhelm.scope") != SCOPE
                or labels.get("cloudhelm.operation_id") != self.operation_id
                or labels.get("cloudhelm.method") != METHOD):
            raise ProbeFailure("python_dependency_container_ownership_mismatch")
        return metadata

    def _context(self) -> Path:
        receipt = verify_seed(self.seed, PythonDependencyInput())
        context = self.directory / "context"
        context.mkdir(mode=0o700)
        files = reference_inputs() | {"Dockerfile": RECIPE.read_bytes(),
            "derived-pyproject.toml": derived_project(),
            "expected-distributions.json": json.dumps(receipt["distributions"], sort_keys=True).encode("utf-8")}
        for name, data in files.items():
            descriptor = os.open(context / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        context.chmod(0o500)
        return context

    def _binds(self) -> dict[str, str]:
        return {"/probe/context": str(self.directory / "context"),
                "/probe/base": str(self.directory / "base-layout"),
                "/probe/python-seed": str(self.seed)}

    @staticmethod
    def _tmpfs() -> dict[str, tuple[int, str]]:
        return {"/home/user/.local/share/buildkit": (STATE_BYTES, "0700"),
                "/run/user/1000": (TEMP_BYTES, "0700"), "/tmp": (TEMP_BYTES, "1777"),
                "/probe/output": (OUTPUT_BYTES, "0700")}

    def create(self) -> None:
        for scope in (SCOPE, "p1-offline-image-probe", "p1-runner-probe"):
            existing = self.client.run("ps", "--all", "--quiet", "--filter", f"label=cloudhelm.scope={scope}")
            if existing.stdout.strip():
                raise ProbeFailure("python_dependency_previous_execution_requires_reconciliation")
        self._context()
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
            raise ProbeFailure("python_dependency_container_identity_unavailable")
        self.client.run("start", self.container_id, timeout=self.remaining())
        self._wait_for_worker()

    def observe_boundary(self) -> dict:
        metadata = self.metadata()
        host, mounts = metadata["HostConfig"], metadata["Mounts"]
        binds = {item["Destination"]: item["Source"] for item in mounts if item["Type"] == "bind" and not item["RW"]}
        expected_tmpfs = {path: size for path, (size, _) in self._tmpfs().items()} | {"/dev/shm": SHM_BYTES}
        if (binds != self._binds() or sum(item["Type"] == "bind" for item in mounts) != 3
                or any(item["Type"] not in ("bind", "tmpfs")
                       or item["Destination"] not in set(binds) | set(expected_tmpfs) for item in mounts)
                or metadata["Config"]["User"] != "1000:1000"
                or not host["ReadonlyRootfs"] or host["Privileged"] or host.get("Devices") or host.get("CapAdd")
                or host["NetworkMode"] != "none" or host["IpcMode"] != "private"
                or set(host["Tmpfs"]) != set(expected_tmpfs) - {"/dev/shm"}):
            raise ProbeFailure("python_dependency_container_boundary_mismatch")
        pid = metadata["State"]["Pid"]
        groups = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        unified = next((line[3:] for line in groups if line.startswith("0::/")), None)
        if unified is None:
            raise ProbeFailure("python_dependency_unified_cgroup_unavailable")
        self.cgroup = Path("/sys/fs/cgroup") / unified.lstrip("/")
        if not self.cgroup.resolve().is_relative_to(Path("/sys/fs/cgroup")):
            raise ProbeFailure("python_dependency_cgroup_path_invalid")
        expected = {"cpu.max": f"{CPU_QUOTA} {CPU_PERIOD}", "memory.max": str(MEMORY_BYTES),
                    "memory.swap.max": "0", "pids.max": str(PIDS_LIMIT)}
        observed = {name: (self.cgroup / name).read_text(encoding="utf-8").strip() for name in expected}
        if observed != expected:
            raise ProbeFailure("python_dependency_cgroup_limits_mismatch")
        storage = {}
        for path, expected_size in expected_tmpfs.items():
            values = self.execute("stat", "-f", "-c", "%S %b", path).stdout.split()
            storage[path] = int(values[0]) * int(values[1])
            if storage[path] != expected_size:
                raise ProbeFailure("python_dependency_tmpfs_capacity_mismatch")
        self._observe_processes()
        return {"kernel_limits": observed, "outer_tmpfs_bytes": storage,
                "outer_tmpfs_capacity_sum": sum(storage.values()),
                "install_tmpfs_bytes": {"/private-cache": INSTALL_CACHE_BYTES, "/tmp": INSTALL_TEMP_BYTES},
                "network": "none", "readonly_root": True, "source_binds_readonly": True,
                "process_sandbox": True, "snapshotter": "native", "execution_wall_seconds": WALL_SECONDS,
                "security_exceptions": ["seccomp=unconfined", "systempaths=unconfined"]}

    def install(self, manifest_digest: str, distributions: dict) -> dict:
        with ThreadPoolExecutor(max_workers=1) as executor:
            build = executor.submit(self.execute, "buildctl", "--addr", SOCKET, "build",
                "--frontend=dockerfile.v0", "--local=context=/probe/context", "--local=dockerfile=/probe/context",
                "--local=pythonseed=/probe/python-seed", "--opt=context:pythonseed=local:pythonseed",
                "--oci-layout=python=/probe/base", "--opt=context:pythonbase=oci-layout://python@" + manifest_digest,
                "--opt=platform=linux/amd64", "--opt=target=verification", "--no-cache", "--progress=plain",
                "--output=type=local,dest=/probe/output/result", ceiling=180, required=False)
            while not build.done():
                self._observe_processes()
                time.sleep(0.2)
            result = build.result()
        if result.returncode:
            lines = [line for line in (result.stdout + result.stderr).splitlines()
                     if len(line) < 1000 and re.match(r"#\d+\s+\d+\.\d+\s", line)]
            raise ProbeFailure("python_dependency_offline_install_failed", detail=safe_diagnostic("\n".join(lines)))
        if ("CLOUDHELM_PYTHON_DEPENDENCIES=verified" not in result.stdout + result.stderr
                or "uv 0.11.29" not in result.stdout + result.stderr):
            raise ProbeFailure("python_dependency_install_command_not_observed")
        output = self.execute("cat", "/probe/output/result/dependency-result.json").stdout
        if len(output) > 65536:
            raise ProbeFailure("python_dependency_install_output_exceeded")
        value = json.loads(output)
        expected = {"python": "3.12.13", "distributions": distributions, "psycopg_impl": "binary",
                    "cache_bytes": INSTALL_CACHE_BYTES, "temp_bytes": INSTALL_TEMP_BYTES,
                    "wheelhouse_readonly": True, "no_ipv4_routes": True, "control_paths_absent": True}
        if value != expected:
            raise ProbeFailure("python_dependency_install_result_mismatch")
        project = self.execute("cat", "/probe/output/result/derived-pyproject.toml").stdout.encode("utf-8")
        lock = self.execute("cat", "/probe/output/result/derived-uv.lock").stdout.encode("utf-8")
        derived = verify_derived_inputs(project, lock, distributions)
        target = self.directory / "derived-inputs"
        target.mkdir(mode=0o700)
        for name, data in (("pyproject.toml", project), ("uv.lock", lock)):
            descriptor = os.open(target / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        target.chmod(0o500)
        self._observe_processes()
        return {"checks": value, "derived_inputs": derived, "build_cache_policy": "no-cache", "application_started": False,
                "database_started": False, "retained_build_state_bytes": 0}

    def stopped_resources(self) -> dict:
        stopped = self.stop_and_remove()
        return {"confirmation": stopped.model_dump(mode="json"),
                "process_resources_released": stopped.status == "verified",
                "memory_peak_bytes": getattr(self, "memory_peak", None),
                "private_builder_and_install_cache_removed": stopped.status == "verified"}
