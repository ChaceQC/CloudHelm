"""The fixed three-service artifact runtime; no build or candidate mounts are accepted."""

from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from packages.contracts.p1.development_environment import EnvironmentArtifactSet

from .artifact_environment_docker import METHOD, SCOPE, docker, engine, metadata, stop
from .artifact_environment_proxy import LoopbackEntrance
from .toolchain import ProbeFailure, safe_diagnostic

LIMITS = {"postgres": (256 * 1024**2, 50000, 64), "backend": (512 * 1024**2, 75000, 128),
          "frontend": (128 * 1024**2, 25000, 64)}
TMPFS = {"postgres": {"/tmp": 16 * 1024**2, "/var/run/postgresql": 4 * 1024**2},
         "backend": {"/tmp": 16 * 1024**2},
         "frontend": {"/tmp": 8 * 1024**2, "/var/cache/nginx": 16 * 1024**2, "/var/run": 1024**2}}


def _secret_file(path: Path, value: str):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


class ArtifactRuntime:
    def __init__(self, directory: Path, operation_id: str, group, artifacts: EnvironmentArtifactSet, image_ids: dict):
        self.directory, self.operation_id, self.group, self.artifacts = directory, operation_id, group, artifacts
        self.image_ids = image_ids
        self.containers: dict[str, str] = {}
        self.network_id: str | None = None
        self.entrance: str | None = None
        self.proxy = None
        self.mount_descriptors: dict[str, int] = {}
        self.mount_sources: dict[str, str] = {}
        self.verified_mounts: dict[str, dict] = {}
        self.startup_threads = {}
        self.startup_results = {}
        self.owner_password, self.app_password = secrets.token_hex(32), secrets.token_hex(32)

    def prepare(self):
        (self.directory / "database").mkdir(mode=0o700)
        secret = self.directory / ".secrets"
        secret.mkdir(mode=0o700)
        _secret_file(secret / "owner", self.owner_password)
        _secret_file(secret / "owner.pgpass", "localhost:5432:reference_notes:reference_owner:" + self.owner_password + "\n")
        for name in ("database", ".secrets"):
            descriptor = os.open(self.directory / name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.mount_descriptors[name] = descriptor
            # The root wrapper shares the daemon's mount namespace. Keep the inode
            # pinned and verify it inside the container after the controlled bind.
            self.mount_sources[name] = str(self.directory / name)
        # The application secret is kept in memory and sent only in Docker's JSON request body.
        value = engine("POST", "/networks/create", {"Name": "cloudhelm-" + self.operation_id,
            "Driver": "bridge", "Internal": True, "CheckDuplicate": True,
            "Labels": {"cloudhelm.operation_id": self.operation_id, "cloudhelm.method": METHOD}})
        self.network_id = value["Id"]
        network = engine("GET", "/networks/" + self.network_id)
        if not network.get("Internal") or network.get("Driver") != "bridge":
            raise ProbeFailure("artifact_environment_internal_network_unconfirmed")

    def _configuration(self, role: str, *, migrate=False) -> dict:
        memory, cpu, pids = LIMITS[role]
        host = {"ReadonlyRootfs": True, "NetworkMode": self.network_id, "CgroupParent": self.group.unit,
            "Memory": memory, "MemorySwap": memory, "CpuPeriod": 100000, "CpuQuota": cpu,
            "PidsLimit": pids, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
            "IpcMode": "private", "ShmSize": 64 * 1024**2 if role == "postgres" else 1024**2,
            "LogConfig": {"Type": "none", "Config": {}},
            "RestartPolicy": {"Name": "no"}, "DnsOptions": ["timeout:1", "attempts:1"],
            "Tmpfs": {path: f"rw,nosuid,nodev,noexec,size={size},uid=1000,gid=1000,mode=1777"
                      for path, size in TMPFS[role].items()}}
        if role == "frontend":
            host["CapAdd"] = ["SETUID", "SETGID", "CHOWN"]
        configuration = {"Image": self.image_ids[role], "User": "1000:1000" if role == "postgres" else "0:0",
            "Labels": {"cloudhelm.operation_id": self.operation_id, "cloudhelm.method": METHOD,
                       "cloudhelm.scope": SCOPE, "cloudhelm.role": role},
            "HostConfig": host, "NetworkingConfig": {"EndpointsConfig": {
                self.network_id: {"Aliases": [role]}}}}
        if role == "postgres":
            host["Mounts"] = [{"Type": "bind", "Source": self.mount_sources["database"],
                "Target": "/var/lib/postgresql/data", "ReadOnly": False},
                {"Type": "bind", "Source": self.mount_sources[".secrets"],
                 "Target": "/run/cloudhelm-secrets", "ReadOnly": True}]
            configuration["Env"] = ["POSTGRES_DB=reference_notes", "POSTGRES_USER=reference_owner",
                "POSTGRES_PASSWORD_FILE=/run/cloudhelm-secrets/owner",
                "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=scram-sha-256"]
            configuration["Cmd"] = ["postgres", "-c", "max_connections=30", "-c", "shared_buffers=32MB",
                "-c", "log_min_messages=panic", "-c", "log_statement=none"]
        elif role == "backend":
            username, password = ("reference_owner", self.owner_password) if migrate else ("reference_app", self.app_password)
            configuration["Env"] = [f"DATABASE_URL=postgresql+psycopg://{username}:{password}@postgres:5432/reference_notes",
                                    "PYTHONDONTWRITEBYTECODE=1"]
            if migrate:
                configuration["Entrypoint"] = ["alembic"]
                configuration["Cmd"] = ["upgrade", "0002_add_updated_at_index"]
        else:
            configuration["ExposedPorts"] = {"80/tcp": {}}
        return configuration

    def create(self, role: str, *, migrate=False):
        name = "cloudhelm-" + self.operation_id + "-" + ("migrate" if migrate else role)
        value = engine("POST", "/containers/create?name=" + name, self._configuration(role, migrate=migrate))
        identity = value["Id"]
        self.containers["migrate" if migrate else role] = identity
        return identity

    def start(self, role: str):
        identity = self.containers[role]
        before = metadata(identity, self.operation_id)
        expected_role = "backend" if role == "migrate" else role
        if before["Image"] != self.image_ids[expected_role] or before["State"]["Running"]:
            raise ProbeFailure("artifact_environment_start_identity_or_state_mismatch")
        self.group.observe()
        self.verified_mounts.pop(role, None)
        if role in {"postgres", "frontend"}:
            self.startup_results[role] = None

            def attach_start():
                try:
                    self.startup_results[role] = docker("start", "--attach", identity, timeout=900, required=False)
                except ProbeFailure as failure:
                    self.startup_results[role] = failure

            self.startup_threads[role] = threading.Thread(target=attach_start, daemon=True)
            self.startup_threads[role].start()
            for _ in range(100):
                if metadata(identity, self.operation_id)["State"]["Running"]:
                    return
                if self.startup_results[role] is not None:
                    self._startup_failure(role)
                time.sleep(0.05)
            raise ProbeFailure("artifact_environment_database_start_not_observed")
        engine("POST", "/containers/" + identity + "/start", expected=(204,))

    def _startup_failure(self, role: str):
        if role in self.startup_threads:
            self.startup_threads[role].join(timeout=2)
        result = self.startup_results.get(role)
        if isinstance(result, ProbeFailure):
            raise result
        diagnostic = role + "_process_exited"
        if result is not None:
            output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            if self.owner_password not in output and self.app_password not in output:
                lines = [line for line in output.splitlines()
                         if any(word in line.lower() for word in ("error", "fatal", "denied", "cannot", "could not", "failed"))]
                diagnostic = safe_diagnostic("\n".join(lines)) or diagnostic
        raise ProbeFailure("artifact_environment_" + role + "_startup_failed", diagnostic)

    def _verify_capacities(self, role: str, actual_role: str):
        if role in self.verified_mounts:
            return self.verified_mounts[role]
        observed = {}
        for path, size in (TMPFS[actual_role] | {"/dev/shm": 64 * 1024**2 if actual_role == "postgres" else 1024**2}).items():
            try:
                values = docker("exec", self.containers[role], "stat", "-f", "-c", "%S %b", path).stdout.split()
            except ProbeFailure:
                if role in self.startup_threads and not metadata(self.containers[role], self.operation_id)["State"]["Running"]:
                    self._startup_failure(role)
                raise
            if len(values) != 2 or int(values[0]) * int(values[1]) != size:
                raise ProbeFailure("artifact_environment_tmpfs_capacity_mismatch")
            observed[path] = size
        if actual_role == "postgres":
            for name, destination in (("database", "/var/lib/postgresql/data"), (".secrets", "/run/cloudhelm-secrets")):
                values = docker("exec", self.containers[role], "stat", "-c", "%d %i", destination).stdout.split()
                pinned = os.fstat(self.mount_descriptors[name])
                if len(values) != 2 or (int(values[0]), int(values[1])) != (pinned.st_dev, pinned.st_ino):
                    raise ProbeFailure("artifact_environment_bound_storage_inode_mismatch")
        self.verified_mounts[role] = observed
        return observed

    def observe(self, role: str) -> dict:
        value = metadata(self.containers[role], self.operation_id)
        actual_role = "backend" if role == "migrate" else role
        host, state = value["HostConfig"], value["State"]
        if role in {"postgres", "frontend"} and not state["Running"]:
            self._startup_failure(role)
        memory, cpu, pids = LIMITS[actual_role]
        checks = {"running": state["Running"] and state["Pid"] > 0,
            "image": value["Image"] in {self.image_ids[actual_role], getattr(self.artifacts, actual_role).config.digest},
            "requested_image": value["Config"]["Image"] == self.image_ids[actual_role],
            "user": value["Config"]["User"] == ("1000:1000" if actual_role == "postgres" else "0:0"),
            "readonly": host["ReadonlyRootfs"],
            "parent": host["CgroupParent"] == self.group.unit, "memory": host["Memory"] == memory,
            "swap": host["MemorySwap"] == memory, "cpu": host["CpuQuota"] == cpu and host["CpuPeriod"] == 100000,
            "pids": host["PidsLimit"] == pids, "privilege": not host.get("Privileged"),
            "caps": {value.removeprefix("CAP_") for value in host.get("CapAdd") or []}
                    == ({"SETUID", "SETGID", "CHOWN"} if actual_role == "frontend" else set())
                    and set(host.get("CapDrop") or []) == {"ALL"},
            "devices": not host.get("Devices"), "network": host["NetworkMode"] == self.network_id,
            "logs": host["LogConfig"]["Type"] == "none"}
        if not all(checks.values()):
            raise ProbeFailure("artifact_environment_container_boundary_mismatch",
                               ",".join(name for name, passed in checks.items() if not passed))
        lines = Path(f'/proc/{state["Pid"]}/cgroup').read_text(encoding="utf-8").splitlines()
        group = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/") for line in lines if line.startswith("0::/")), None)
        if group is None or not group.is_relative_to(self.group.path):
            raise ProbeFailure("artifact_environment_process_outside_parent")
        expected = {"cpu.max": f"{cpu} 100000", "memory.max": str(memory),
                    "memory.swap.max": "0", "pids.max": str(pids)}
        limits = {name: (group / name).read_text(encoding="utf-8").strip() for name in expected}
        if limits != expected:
            raise ProbeFailure("artifact_environment_child_kernel_limits_mismatch")
        configured = self._configuration(actual_role, migrate=role == "migrate")["HostConfig"]
        if (host["Tmpfs"] != configured["Tmpfs"] or host["ShmSize"] != configured["ShmSize"]
                or host.get("SecurityOpt") != ["no-new-privileges:true"]
                or host["IpcMode"] != "private" or host["RestartPolicy"]["Name"] != "no"):
            raise ProbeFailure("artifact_environment_runtime_isolation_mismatch")
        binds = {item["Destination"]: (item["Source"], not item["RW"])
                 for item in value["Mounts"] if item["Type"] == "bind"}
        expected_binds = {item["Target"]: (item["Source"], item["ReadOnly"])
                          for item in configured.get("Mounts", [])}
        allowed_tmpfs = set(TMPFS[actual_role]) | {"/dev/shm"}
        if (binds != expected_binds or any(item["Type"] not in {"bind", "tmpfs"}
                or (item["Type"] == "tmpfs" and item["Destination"] not in allowed_tmpfs)
                for item in value["Mounts"])):
            raise ProbeFailure("artifact_environment_mount_boundary_mismatch")
        if role == "frontend":
            endpoints = [entry for entry in value["NetworkSettings"]["Networks"].values()
                         if entry["NetworkID"] == self.network_id]
            if len(endpoints) != 1 or host.get("PortBindings"):
                raise ProbeFailure("artifact_environment_frontend_network_unconfirmed")
            if self.proxy is None:
                self.proxy = LoopbackEntrance(endpoints[0]["IPAddress"])
            elif self.proxy.address != endpoints[0]["IPAddress"]:
                raise ProbeFailure("artifact_environment_frontend_address_drift")
            self.entrance = self.proxy.url
        elif host.get("PortBindings"):
            raise ProbeFailure("artifact_environment_private_service_has_host_port")
        return {"container_id": self.containers[role], "image_id": value["Image"],
                "running": True, "kernel_limits": limits, "parent_verified": True, "root_readonly": True,
                "user": value["Config"]["User"], "cap_drop": host["CapDrop"], "cap_add": host.get("CapAdd") or [],
                "platform_entrance": ({"kind": "local_validation_loopback_tcp", "url": self.entrance,
                    "target_container_id": self.containers[role], "target_port": 80, "active_connections_max": 1,
                    "pending_connections_max": 8, "connection_bytes_max": 8 * 1024**2,
                    "connection_seconds_max": 15, "platform_overhead": True, "p2_preview": False}
                    if role == "frontend" else None),
                "tmpfs_capacities": self._verify_capacities(role, actual_role),
                "data_mount_inode_verified": actual_role == "postgres"}

    def sql(self, statement: str, *, required=True):
        return docker("exec", "--env=PGPASSFILE=/run/cloudhelm-secrets/owner.pgpass", "-i",
            self.containers["postgres"], "psql", "--no-psqlrc", "--quiet", "--tuples-only", "--no-align",
            "--host=localhost", "--username=reference_owner", "--dbname=reference_notes", "--set=ON_ERROR_STOP=1",
            input_bytes=statement.encode("utf-8"), required=required)

    def wait_database(self):
        for _ in range(60):
            self.observe("postgres")
            query = self.sql("SELECT 1;", required=False)
            if query.returncode == 0 and query.stdout.strip() == b"1":
                return
            time.sleep(0.5)
        raise ProbeFailure("artifact_environment_database_not_ready")

    def migrate(self):
        self.create("backend", migrate=True)
        self.start("migrate")
        for _ in range(60):
            value = metadata(self.containers["migrate"], self.operation_id)
            if not value["State"]["Running"]:
                if value["State"]["ExitCode"] != 0:
                    raise ProbeFailure("artifact_environment_migration_failed")
                self.remove("migrate")
                return
            try:
                self.observe("migrate")
            except (FileNotFoundError, ProbeFailure):
                # The bounded one-shot may exit between inspect and kernel sampling.
                after = metadata(self.containers["migrate"], self.operation_id)["State"]
                if after["Running"] or after["ExitCode"] != 0:
                    raise
            time.sleep(0.5)
        raise ProbeFailure("artifact_environment_migration_deadline")

    def wait_ready(self):
        self.observe("frontend")
        opener = build_opener(ProxyHandler({}))
        for _ in range(60):
            for role in ("postgres", "backend", "frontend"):
                self.observe(role)
            try:
                with opener.open(self.entrance + "/ready", timeout=2) as response:
                    if response.status == 200:
                        return
            except (URLError, HTTPError, OSError):
                pass
            time.sleep(0.5)
        raise ProbeFailure("artifact_environment_application_not_ready")

    def stop(self, role: str):
        if role == "frontend":
            self.entrance = None
            if self.proxy is not None:
                self.proxy.close()
                self.proxy = None
        result = stop(self.containers[role], self.operation_id)
        if role in self.startup_threads:
            self.startup_threads[role].join(timeout=5)
            if self.startup_threads[role].is_alive():
                raise ProbeFailure("artifact_environment_attach_stop_unconfirmed")
        return result

    def remove(self, role: str):
        stopped = self.stop(role)
        identity = self.containers[role]
        engine("DELETE", "/containers/" + identity + "?v=1", expected=(204,))
        del self.containers[role]
        return stopped

    def close_mount_descriptors(self):
        if self.containers:
            raise ProbeFailure("artifact_environment_mounts_still_have_writers")
        for descriptor in self.mount_descriptors.values():
            os.close(descriptor)
        self.mount_descriptors.clear()
