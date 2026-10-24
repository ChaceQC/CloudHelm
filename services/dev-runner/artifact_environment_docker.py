"""Secret-silent local Docker operations and one dedicated transient systemd slice."""

from __future__ import annotations

import http.client
import fcntl
import json
import os
import re
import socket
import stat
import subprocess
from pathlib import Path

from .toolchain import DOCKER, ProbeFailure, RUNTIME_ROOT, classify_diagnostic, private_directory, safe_diagnostic
from modules.execution.docker_endpoint import socket_path

CPU_QUOTA, CPU_PERIOD = 150000, 100000
MEMORY_BYTES, PIDS_LIMIT = 896 * 1024**2, 256
ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
SCOPE = "p1-artifact-environment"
METHOD = "p1-artifact-environment-r1"


class _DockerConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=30)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(socket_path())


def engine(method: str, path: str, payload: dict | None = None, *, expected=(200, 201, 204)):
    """Docker errors and response bodies never become diagnostics or logs."""
    from .resource_context import current_group

    group = current_group()
    if group is not None and method == "POST" and path == "/networks/create":
        payload = dict(payload)
        payload["Labels"] = dict(payload.get("Labels") or {}) | {"cloudhelm.resource-binding": group.binding}
    connection = _DockerConnection()
    try:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
        connection.request(method, path, body=raw, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = response.read(2_000_001)
        if response.status not in expected or len(data) > 2_000_000:
            stage = "container_start" if path.endswith("/start") else "request"
            raise ProbeFailure("artifact_environment_docker_" + stage + "_rejected",
                "http_" + str(response.status), safe_diagnostic(data.decode("utf-8", errors="replace")))
        value = json.loads(data) if data else None
        if group is not None and method == "POST" and path == "/networks/create":
            group.authorize_network(value["Id"])
        return value
    except (OSError, ValueError, http.client.HTTPException):
        raise ProbeFailure("artifact_environment_docker_unavailable") from None
    finally:
        connection.close()


def command(arguments: list[str], *, input_bytes: bytes | None = None, stdin=None,
            stdout=None, timeout=30, required=True, preexec_fn=None) -> subprocess.CompletedProcess:
    """No command output is echoed; inputs may contain short-lived credentials."""
    try:
        result = subprocess.run(arguments, input=input_bytes, stdin=stdin, stdout=stdout or subprocess.PIPE,
            stderr=subprocess.PIPE, env=ENVIRONMENT, timeout=timeout, check=False, preexec_fn=preexec_fn)
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeFailure("artifact_environment_fixed_command_unavailable") from None
    if (required and result.returncode) or len(result.stderr) > 65536:
        executable = Path(arguments[0]).name
        action = arguments[5] if executable == "docker" and len(arguments) > 5 else executable
        if action not in {"manifest", "image", "pull", "exec", "busctl", "systemctl"}:
            action = "fixed_command"
        raise ProbeFailure("artifact_environment_" + action + "_rejected",
                           classify_diagnostic(result.stderr.decode("utf-8", errors="replace")))
    if isinstance(result.stdout, bytes) and len(result.stdout) > 2_000_000:
        raise ProbeFailure("artifact_environment_fixed_output_exceeded")
    return result


def docker(*arguments: str, **kwargs):
    directory = Path("/home/cloudhelm/.local/state/cloudhelm/artifact-public-docker")
    private_directory(directory)
    if (directory / "config.json").exists():
        raise ProbeFailure("artifact_environment_public_docker_config_not_empty")
    return command([DOCKER, "--config", str(directory), "--host", "unix://" + socket_path(), *arguments], **kwargs)


class EnvironmentGroup:
    def __init__(self, storage_id: str):
        if not re.fullmatch(r"dev-storage-[0-9a-f]{32}", storage_id):
            raise ProbeFailure("artifact_environment_storage_identity_invalid")
        self.unit = "cloudhelm_p1_artifact_" + storage_id.removeprefix("dev-storage-") + ".slice"
        self.path: Path | None = None
        self.created = False
        self.external = False
        self.lock: int | None = None
        from .resource_context import current_group

        self.resource_binding = current_group()
        if self.resource_binding is not None:
            if self.resource_binding.registration.storage.storage_id != storage_id:
                raise ProbeFailure("artifact_environment_resource_storage_mismatch")
            self.unit = self.resource_binding.unit
            self.path = self.resource_binding.path

    def acquire(self):
        if self.lock is not None:
            return
        private_directory(RUNTIME_ROOT)
        descriptor = os.open(RUNTIME_ROOT / "execution.lock",
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_uid != os.getuid() or observed.st_mode & 0o077:
            os.close(descriptor)
            raise ProbeFailure("artifact_environment_execution_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            raise ProbeFailure("artifact_environment_execution_group_busy") from None
        self.lock = descriptor

    def create(self):
        if self.resource_binding is None:
            raise ProbeFailure("artifact_environment_legacy_start_retired")
        self.acquire()
        result = self.resource_binding.observe()
        self.created, self.external = True, True
        return result

    def prepare_unit(self):
        """Root maintenance prepares the single operation's transient unit."""
        raise ProbeFailure("artifact_environment_use_registered_resource_host")

    def observe(self) -> dict:
        if self.resource_binding is not None:
            return self.resource_binding.observe()
        if self.path is None:
            raise ProbeFailure("artifact_environment_group_not_prepared")
        expected = {"cpu.max": f"{CPU_QUOTA} {CPU_PERIOD}", "memory.max": str(MEMORY_BYTES),
                    "pids.max": str(PIDS_LIMIT)}
        actual = {name: (self.path / name).read_text(encoding="utf-8").strip() for name in expected}
        if actual != expected:
            raise ProbeFailure("artifact_environment_parent_hard_limits_mismatch")
        return {"unit": self.unit, "kernel_limits": actual,
                "memory_peak_bytes": int((self.path / "memory.peak").read_text(encoding="utf-8")),
                "pids_peak": int((self.path / "pids.peak").read_text(encoding="utf-8"))}

    def dispose(self):
        if self.resource_binding is not None:
            # The domain stops its writers first. The coordinator owns the
            # daemon/whole-group stop; suspend retains this stable binding.
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None
            self.created = False
            return {"resource_owner_retained": True, "unit": self.unit}
        if not self.created:
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None
            return {"created": False}
        if self.external:
            if "populated 0" not in (self.path / "cgroup.events").read_text(encoding="utf-8").splitlines():
                raise ProbeFailure("artifact_environment_parent_still_populated")
            result = self.observe() | {"root_stop_pending": True, "populated": False}
            self.created = False
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None
            return result
        if self.path is not None and (self.path / "cgroup.events").exists():
            events = (self.path / "cgroup.events").read_text(encoding="utf-8")
            if "populated 0" not in events.splitlines():
                raise ProbeFailure("artifact_environment_parent_still_populated")
        result = self.observe() if self.path is not None and self.path.exists() else {"parent_already_absent": True}
        if os.getuid() != 0:
            raise ProbeFailure("artifact_environment_explicit_root_stop_required")
        command(["/usr/bin/systemctl", "stop", self.unit])
        if self.path is not None and self.path.exists():
            raise ProbeFailure("artifact_environment_parent_stop_unconfirmed")
        self.created = False
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        return result | {"stopped_and_removed": True}


def metadata(container_id: str, operation_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", container_id):
        raise ProbeFailure("artifact_environment_container_id_invalid")
    value = engine("GET", "/containers/" + container_id + "/json")
    labels = value["Config"].get("Labels") or {}
    if labels.get("cloudhelm.operation_id") != operation_id or labels.get("cloudhelm.method") != METHOD:
        raise ProbeFailure("artifact_environment_container_ownership_mismatch")
    return value  # Trusted caller must never serialize Config.Env or the complete object.


def stop(container_id: str, operation_id: str) -> dict:
    value = metadata(container_id, operation_id)
    pid = value["State"]["Pid"]
    original_group = None
    if pid:
        lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        original_group = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                               for line in lines if line.startswith("0::/")), None)
    engine("POST", "/containers/" + container_id + "/stop?t=10", expected=(204, 304))
    observed = metadata(container_id, operation_id)["State"]
    if observed["Running"] or observed["Pid"] != 0 or observed.get("Paused") or observed.get("Restarting"):
        raise ProbeFailure("artifact_environment_physical_stop_unconfirmed")
    if original_group is not None and (original_group / "cgroup.events").exists():
        if "populated 0" not in (original_group / "cgroup.events").read_text(encoding="utf-8").splitlines():
            raise ProbeFailure("artifact_environment_stopped_group_populated")
    return {"container_id": container_id, "pid_zero": True, "running": False,
            "original_cgroup_unpopulated_or_removed": True}
