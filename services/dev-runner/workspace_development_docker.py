"""Fixed Docker boundary for the one supported mutable Workspace profile."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from packages.contracts.p1.development_environment import POSTGRES_REFERENCE
from packages.contracts.p1.workspace_candidates import RegisteredWorkspaceReader
from modules.workspaces.candidate_writers import process_start_ticks

from .artifact_environment_docker import docker, engine
from .offline_images import SOURCE_DIGEST, SOURCE_REFERENCE
from .toolchain import DockerClient, ProbeFailure
from .workspace_development_bootstrap import bootstrap_command

SCOPE = "p1-workspace-development"
METHOD = "p1-workspace-development-r1"
PROFILE = "notes-backend-dev-r1"
MIGRATION_REVISION = "0002_add_updated_at_index"
DATASET_REVISIONS = {"reference-synthetic-r1", "reference-synthetic-r2"}
DATA_REVISION = "reference-synthetic-r1"
POSTGRES_IMAGE_DIGEST = POSTGRES_REFERENCE.rsplit("@", 1)[1]
PYTHON_IMAGE_DIGEST = SOURCE_DIGEST
DATABASE_LIMITS = (256 * 1024**2, 50_000, 64)
BACKEND_LIMITS = (512 * 1024**2, 75_000, 128)
DATABASE_TMPFS = {
    "/tmp": "rw,nosuid,nodev,noexec,size=16777216,uid=1000,gid=1000,mode=1777",
    "/var/run/postgresql": "rw,nosuid,nodev,noexec,size=4194304,uid=1000,gid=1000,mode=1777",
}
BACKEND_TMPFS = {
    "/tmp": "rw,nosuid,nodev,noexec,size=16777216,uid=1000,gid=1000,mode=1777",
    "/environment": "rw,nosuid,nodev,exec,size=603979776,uid=1000,gid=1000,mode=0755",
}


def environment_name(environment_id: str) -> str:
    if not isinstance(environment_id, str) or not 1 <= len(environment_id) <= 160:
        raise ProbeFailure("workspace_development_identity_invalid")
    return "workspace-dev-" + hashlib.sha256(environment_id.encode("utf-8")).hexdigest()[:24]


def ensure_fixed_image(client: DockerClient, reference: str, digest: str, *, label: str) -> str:
    """Load only an immutable, already expected linux/amd64 image reference."""
    if reference not in {SOURCE_REFERENCE, POSTGRES_REFERENCE}:
        raise ProbeFailure("workspace_development_image_not_allowlisted")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ProbeFailure("workspace_development_image_digest_invalid")
    present = client.run("image", "inspect", reference, "--format", "{{.Id}}", required=False)
    if present.returncode:
        client.run("pull", "--platform=linux/amd64", reference, timeout=240)
    try:
        descriptor = json.loads(client.run("image", "inspect", reference,
            "--format", "{{json .Descriptor}}").stdout)
        image_id = json.loads(client.run("image", "inspect", reference,
            "--format", "{{json .Id}}").stdout)
        platform = [json.loads(item) for item in client.run("image", "inspect", reference,
            "--format", "{{json .Os}} {{json .Architecture}}").stdout.split()]
    except (ValueError, TypeError):
        raise ProbeFailure("workspace_development_" + label + "_image_observation_invalid") from None
    if (descriptor.get("digest") != digest or not isinstance(image_id, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
            or platform != ["linux", "amd64"]):
        raise ProbeFailure("workspace_development_" + label + "_image_identity_mismatch")
    return image_id


def inspect_fixed_image(client: DockerClient, reference: str, digest: str) -> str | None:
    """Read only; unlike ensure_fixed_image this never pulls or changes images."""
    if reference not in {SOURCE_REFERENCE, POSTGRES_REFERENCE} or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ProbeFailure("workspace_development_image_not_allowlisted")
    present = client.run("image", "inspect", reference, "--format", "{{.Id}}", required=False)
    if present.returncode:
        return None
    try:
        descriptor = json.loads(client.run("image", "inspect", reference,
            "--format", "{{json .Descriptor}}").stdout)
        image_id = json.loads(client.run("image", "inspect", reference,
            "--format", "{{json .Id}}").stdout)
        platform = [json.loads(item) for item in client.run("image", "inspect", reference,
            "--format", "{{json .Os}} {{json .Architecture}}").stdout.split()]
    except (ValueError, TypeError):
        return None
    if (descriptor.get("digest") != digest or platform != ["linux", "amd64"]
            or not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)):
        return None
    return image_id


def write_secret(path: Path, value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ProbeFailure("workspace_development_secret_shape_invalid")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value.encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise ProbeFailure("workspace_development_private_configuration_unavailable") from None


class WorkspaceDevelopmentDocker:
    """Owns exact network/container identities; no caller supplies Docker fields."""

    def __init__(self, *, client: DockerClient, environment_id: str, scope_id: str,
                 operation_id: str, cgroup_parent: str, cgroup_path: Path, database_directory: Path,
                 secrets_directory: Path, workspace_source: str, snapshot_source: Path | None,
                 snapshot_digest: str | None, snapshot_bytes: int | None, app_password: str,
                 owner_password: str, data_revision: str = "reference-synthetic-r1"):
        if data_revision not in DATASET_REVISIONS:
            raise ProbeFailure("workspace_development_data_revision_unsupported")
        self.client = client
        self.environment_id = environment_id
        self.operation_id = operation_id
        self.scope_id = scope_id
        self.cgroup_parent = cgroup_parent
        self.cgroup_path = cgroup_path
        self.database_directory = database_directory
        self.secrets_directory = secrets_directory
        self.workspace_source = workspace_source
        self.snapshot_source = snapshot_source
        self.snapshot_digest = snapshot_digest
        self.snapshot_bytes = snapshot_bytes
        self.app_password = app_password
        self.owner_password = owner_password
        self.data_revision = data_revision
        self.images: dict[str, str] = {}
        self.containers: dict[str, str] = {}
        self.network_id: str | None = None
        self.entrance = None

    @property
    def name(self) -> str:
        return environment_name(self.environment_id)

    def _labels(self, role: str | None = None) -> dict[str, str]:
        values = {"cloudhelm.scope": self.scope_id, "cloudhelm.method": METHOD,
                  "cloudhelm.operation_id": self.operation_id,
                  "cloudhelm.environment_id": self.environment_id,
                  "cloudhelm.profile": PROFILE}
        if role is not None:
            values["cloudhelm.role"] = role
        return values

    def ensure_images(self) -> dict[str, str]:
        self.images = {
            "postgres": ensure_fixed_image(self.client, POSTGRES_REFERENCE, POSTGRES_IMAGE_DIGEST,
                label="postgres"),
            "python": ensure_fixed_image(self.client, SOURCE_REFERENCE, PYTHON_IMAGE_DIGEST,
                label="python"),
        }
        return dict(self.images)

    def create_network(self) -> None:
        if self.network_id is not None:
            raise ProbeFailure("workspace_development_network_already_created")
        value = engine("POST", "/networks/create", {
            "Name": self.name, "Driver": "bridge", "Internal": True, "CheckDuplicate": True,
            "Labels": self._labels(),
        })
        self.network_id = value["Id"]
        observed = engine("GET", "/networks/" + self.network_id)
        if (observed.get("Id") != self.network_id or observed.get("Internal") is not True
                or observed.get("Driver") != "bridge" or observed.get("Labels") != self._labels()):
            raise ProbeFailure("workspace_development_internal_network_unconfirmed")

    def _host(self, role: str, tmpfs: dict[str, str]) -> dict:
        if self.network_id is None:
            raise ProbeFailure("workspace_development_network_required")
        memory, cpu, pids = DATABASE_LIMITS if role == "postgres" else BACKEND_LIMITS
        return {
            "ReadonlyRootfs": True, "NetworkMode": self.network_id,
            "CgroupParent": self.cgroup_parent, "Memory": memory, "MemorySwap": memory,
            "CpuPeriod": 100000, "CpuQuota": cpu, "PidsLimit": pids,
            "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
            "IpcMode": "private", "ShmSize": 64 * 1024**2 if role == "postgres" else 1024**2,
            "LogConfig": {"Type": "none", "Config": {}}, "RestartPolicy": {"Name": "no"},
            "DnsOptions": ["timeout:1", "attempts:1"], "Tmpfs": tmpfs,
        }

    def _base_config(self, role: str, image: str, tmpfs: dict[str, str]) -> dict:
        value = {"Image": image, "User": "1000:1000", "Labels": self._labels(role),
                 "HostConfig": self._host(role, tmpfs),
                 "NetworkingConfig": {"EndpointsConfig": {
                     self.network_id: {"Aliases": [role]}}}}
        if role != "postgres":
            value["WorkingDir"] = "/workspace/backend"
        return value

    def create_database(self) -> str:
        if self.containers or self.images.get("postgres") is None:
            raise ProbeFailure("workspace_development_database_create_order_invalid")
        config = self._base_config("postgres", self.images["postgres"], DATABASE_TMPFS)
        config["HostConfig"]["Mounts"] = [
            {"Type": "bind", "Source": str(self.database_directory),
             "Target": "/var/lib/postgresql/data", "ReadOnly": False},
            {"Type": "bind", "Source": str(self.secrets_directory),
             "Target": "/run/cloudhelm-secrets", "ReadOnly": True},
        ]
        config["Env"] = ["POSTGRES_DB=reference_notes", "POSTGRES_USER=reference_owner",
            "POSTGRES_PASSWORD_FILE=/run/cloudhelm-secrets/owner",
            "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=scram-sha-256"]
        config["Cmd"] = ["postgres", "-c", "max_connections=30", "-c", "shared_buffers=32MB",
            "-c", "log_min_messages=panic", "-c", "log_statement=none"]
        return self._create("postgres", config)

    def _bootstrap_mounts(self) -> list[dict]:
        if (self.snapshot_source is None or self.snapshot_digest is None or self.snapshot_bytes is None
                or not self.workspace_source.startswith("/") or self.snapshot_source.is_symlink()
                or not self.snapshot_source.is_file() or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.snapshot_digest)
                or self.snapshot_source.name != "dependencies.tar.gz"
                or type(self.snapshot_bytes) is not int or not 0 < self.snapshot_bytes <= 384 * 1024**2
                or self.snapshot_source.stat().st_size != self.snapshot_bytes):
            raise ProbeFailure("workspace_development_dependency_snapshot_invalid")
        return [
            {"Type": "bind", "Source": self.workspace_source,
             "Target": "/workspace", "ReadOnly": True},
            {"Type": "bind", "Source": str(self.snapshot_source),
             "Target": "/workspace-cache/dependencies.tar.gz", "ReadOnly": True},
        ]

    def _database_url(self, username: str, password: str) -> str:
        if username not in {"reference_owner", "reference_app"} or not re.fullmatch(r"[0-9a-f]{64}", password):
            raise ProbeFailure("workspace_development_database_identity_invalid")
        return f"postgresql+psycopg://{username}:{password}@postgres:5432/reference_notes"

    def create_migration(self, revision: str = MIGRATION_REVISION) -> str:
        if revision != MIGRATION_REVISION or self.images.get("python") is None or self.network_id is None:
            raise ProbeFailure("workspace_development_migration_scope_invalid")
        config = self._base_config("migration", self.images["python"], BACKEND_TMPFS)
        config["HostConfig"]["Mounts"] = self._bootstrap_mounts()
        config["Env"] = ["DATABASE_URL=" + self._database_url("reference_owner", self.owner_password),
            "WORKSPACE_SNAPSHOT_SHA256=" + self.snapshot_digest.removeprefix("sha256:"),
            "PYTHONDONTWRITEBYTECODE=1", "HOME=/tmp"]
        config["Cmd"] = ["/usr/local/bin/python", "-B", "-I", "-c", bootstrap_command(MIGRATION_REVISION)]
        return self._create("migration", config)

    def create_backend(self) -> str:
        if self.images.get("python") is None or self.network_id is None:
            raise ProbeFailure("workspace_development_backend_scope_invalid")
        config = self._base_config("backend", self.images["python"], BACKEND_TMPFS)
        config["ExposedPorts"] = {"8000/tcp": {}}
        config["HostConfig"]["Mounts"] = self._bootstrap_mounts()
        config["Env"] = ["DATABASE_URL=" + self._database_url("reference_app", self.app_password),
            "WORKSPACE_SNAPSHOT_SHA256=" + self.snapshot_digest.removeprefix("sha256:"),
            "CLOUDHELM_DATA_REVISION=" + self.data_revision,
            "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "HOME=/tmp"]
        config["Cmd"] = ["/usr/local/bin/python", "-B", "-I", "-c", bootstrap_command("serve")]
        return self._create("backend", config)

    def _create(self, role: str, config: dict) -> str:
        identity = environment_name(self.environment_id)
        name = identity + "-" + role
        value = engine("POST", "/containers/create?name=" + name, config)
        container_id = value.get("Id")
        if not isinstance(container_id, str) or not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise ProbeFailure("workspace_development_container_identity_invalid")
        self.containers[role] = container_id
        return container_id

    def start(self, role: str) -> None:
        if role not in {"postgres", "backend", "migration"} or role not in self.containers:
            raise ProbeFailure("workspace_development_container_start_scope_invalid")
        engine("POST", "/containers/" + self.containers[role] + "/start", expected=(204,))
        self.verify_container(role, require_running=role != "migration")

    def inspect(self, role: str) -> dict:
        if role not in self.containers:
            raise ProbeFailure("workspace_development_container_not_registered")
        identity = self.containers[role]
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ProbeFailure("workspace_development_container_identity_invalid")
        value = engine("GET", "/containers/" + identity + "/json")
        labels = value.get("Config", {}).get("Labels") or {}
        expected = self._labels(role)
        if any(labels.get(key) != item for key, item in expected.items()):
            raise ProbeFailure("workspace_development_container_ownership_mismatch")
        return value

    def verify_container(self, role: str, *, require_running: bool = True) -> dict:
        value = self.inspect(role)
        host = value["HostConfig"]
        memory, cpu, pids = DATABASE_LIMITS if role == "postgres" else BACKEND_LIMITS
        running = value["State"].get("Running") is True
        if require_running and not running:
            raise ProbeFailure("workspace_development_container_not_running")
        expected_image = self.images["postgres" if role == "postgres" else "python"]
        if role == "backend":
            environment = value["Config"].get("Env") or []
            if "CLOUDHELM_DATA_REVISION=" + self.data_revision not in environment:
                raise ProbeFailure("workspace_development_backend_data_revision_mismatch")
        checks = {
            "image": value["Image"] == expected_image,
            "user": value["Config"].get("User") == "1000:1000",
            "root_readonly": host["ReadonlyRootfs"] is True,
            "network": host["NetworkMode"] == self.network_id,
            "parent": host["CgroupParent"] == self.cgroup_parent,
            "memory": host["Memory"] == memory and host["MemorySwap"] == memory,
            "cpu": host["CpuQuota"] == cpu and host["CpuPeriod"] == 100000,
            "pids": host["PidsLimit"] == pids,
            "capabilities": set(host.get("CapDrop") or []) == {"ALL"} and not host.get("CapAdd"),
            "security": host.get("SecurityOpt") == ["no-new-privileges:true"],
            "ipc": host.get("IpcMode") == "private",
            "logging": host.get("LogConfig", {}).get("Type") == "none",
            "restart": host.get("RestartPolicy", {}).get("Name") == "no",
            "no_host_ports": not host.get("PortBindings"),
            "no_privilege": host.get("Privileged") is not True and not host.get("Devices")
                and host.get("PidMode") != "host",
            "tmpfs": host.get("Tmpfs") == (DATABASE_TMPFS if role == "postgres" else BACKEND_TMPFS),
            "dns": host.get("DnsOptions") == ["timeout:1", "attempts:1"],
        }
        if not all(checks.values()):
            raise ProbeFailure("workspace_development_container_boundary_mismatch",
                ",".join(key for key, passed in checks.items() if not passed))
        configured = self._expected_mounts(role)
        actual = {item["Destination"]: (item["Source"], not item["RW"])
                  for item in value["Mounts"] if item["Type"] == "bind"}
        if actual != configured:
            raise ProbeFailure("workspace_development_container_mount_mismatch")
        if running:
            pid = value["State"].get("Pid")
            if type(pid) is not int or pid <= 1:
                raise ProbeFailure("workspace_development_container_process_unconfirmed")
            try:
                lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
                process_group = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                                      for line in lines if line.startswith("0::/")), None)
                if (process_group is None or process_group == self.cgroup_path
                        or not process_group.is_relative_to(self.cgroup_path)):
                    raise ProbeFailure("workspace_development_process_outside_parent")
                expected_limits = {"cpu.max": f"{cpu} 100000", "memory.max": str(memory),
                                   "memory.swap.max": "0", "pids.max": str(pids)}
                actual_limits = {name: (process_group / name).read_text(encoding="utf-8").strip()
                                 for name in expected_limits}
                if actual_limits != expected_limits:
                    raise ProbeFailure("workspace_development_child_kernel_limits_mismatch")
                if process_start_ticks(pid) <= 0:
                    raise ProbeFailure("workspace_development_container_process_unconfirmed")
            except ProbeFailure:
                raise
            except (OSError, ValueError, IndexError):
                raise ProbeFailure("workspace_development_container_cgroup_observation_failed") from None
        return {"container_id": self.containers[role], "role": role, "running": running,
                "image_id": value["Image"], "readonly_root": True, "parent_verified": True,
                "mounts_verified": True, "host_port_bindings": False}

    def _expected_mounts(self, role: str) -> dict[str, tuple[str, bool]]:
        if role == "postgres":
            return {"/var/lib/postgresql/data": (str(self.database_directory), False),
                    "/run/cloudhelm-secrets": (str(self.secrets_directory), True)}
        if self.snapshot_source is None:
            return {"/workspace": (self.workspace_source, True)}
        return {"/workspace": (self.workspace_source, True),
                "/workspace-cache/dependencies.tar.gz": (str(self.snapshot_source), True)}

    def sql(self, statement: str, *, required: bool = True):
        if "postgres" not in self.containers or not isinstance(statement, str) or len(statement) > 8192:
            raise ProbeFailure("workspace_development_sql_scope_invalid")
        return docker("exec", "--env=PGPASSFILE=/run/cloudhelm-secrets/owner.pgpass", "-i",
            self.containers["postgres"], "psql", "--no-psqlrc", "--quiet", "--tuples-only", "--no-align",
            "--host=localhost", "--username=reference_owner", "--dbname=reference_notes",
            "--set=ON_ERROR_STOP=1", input_bytes=statement.encode("utf-8"), required=required)

    def migration_exit(self) -> int | None:
        value = self.inspect("migration")
        state = value["State"]
        if state.get("Running") is True:
            return None
        code = state.get("ExitCode")
        if type(code) is not int or code < 0:
            raise ProbeFailure("workspace_development_migration_exit_unknown")
        return code

    def remove_exited(self, role: str) -> None:
        value = self.inspect(role)
        if value["State"].get("Running") is True or value["State"].get("Pid") not in (0, None):
            raise ProbeFailure("workspace_development_remove_live_container_forbidden")
        engine("DELETE", "/containers/" + self.containers[role] + "?v=false", expected=(204,))
        del self.containers[role]

    def stop(self, role: str) -> dict:
        value = self.inspect(role)
        state = value["State"]
        pid = state.get("Pid")
        original_group = None
        if type(pid) is int and pid > 1:
            try:
                lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
                original_group = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                    for line in lines if line.startswith("0::/")), None)
            except OSError:
                raise ProbeFailure("workspace_development_process_group_unavailable") from None
        if state.get("Running") is True:
            engine("POST", "/containers/" + self.containers[role] + "/stop?t=10", expected=(204, 304))
        after = self.inspect(role)["State"]
        if (after.get("Running") is True or after.get("Pid") != 0
                or after.get("Paused") or after.get("Restarting")):
            raise ProbeFailure("workspace_development_physical_stop_unconfirmed")
        if original_group is not None:
            try:
                events = (original_group / "cgroup.events").read_text(encoding="utf-8")
            except FileNotFoundError:
                pass
            except OSError:
                raise ProbeFailure("workspace_development_stopped_group_unavailable") from None
            else:
                if "populated 0" not in events.splitlines():
                    raise ProbeFailure("workspace_development_stopped_group_populated")
        return {"container_id": self.containers[role], "role": role,
                "pid_zero": True, "running": False, "group_unpopulated_or_removed": True}

    def remove_network(self) -> None:
        if self.containers:
            raise ProbeFailure("workspace_development_network_has_containers")
        if self.network_id is not None:
            engine("DELETE", "/networks/" + self.network_id, expected=(204,))
            self.network_id = None

    @staticmethod
    def discover_network(environment_id: str, scope_id: str, operation_id: str) -> dict | None:
        if (not re.fullmatch(r"dev-env-[0-9a-f]{32}", environment_id)
                or not isinstance(scope_id, str) or not isinstance(operation_id, str)):
            raise ProbeFailure("workspace_development_network_discovery_identity_invalid")
        filters = ["cloudhelm.method=" + METHOD, "cloudhelm.environment_id=" + environment_id,
                   "cloudhelm.scope=" + scope_id, "cloudhelm.operation_id=" + operation_id]
        path = "/networks?filters=" + quote(json.dumps({"label": filters}, separators=(",", ":")), safe="")
        values = engine("GET", path)
        if len(values) > 1:
            raise ProbeFailure("workspace_development_network_duplicate")
        if not values:
            return None
        identity = values[0].get("Id", "")
        actual = engine("GET", "/networks/" + identity)
        labels = actual.get("Labels") or {}
        if (not re.fullmatch(r"[0-9a-f]{64}", identity) or actual.get("Name") != environment_name(environment_id)
                or actual.get("Internal") is not True or actual.get("Driver") != "bridge"
                or any(labels.get(key) != item for key, item in {
                    "cloudhelm.method": METHOD, "cloudhelm.environment_id": environment_id,
                    "cloudhelm.scope": scope_id, "cloudhelm.operation_id": operation_id,
                    "cloudhelm.profile": PROFILE}.items())):
            raise ProbeFailure("workspace_development_network_identity_mismatch")
        return {"network_id": identity, "name": actual["Name"], "internal": True, "driver": "bridge"}

    def registered_readers(self) -> tuple[RegisteredWorkspaceReader, ...]:
        readers = []
        for role in ("backend", "migration"):
            if role not in self.containers:
                continue
            value = self.inspect(role)
            workspace_mounts = [item for item in value.get("Mounts", [])
                if item.get("Type") == "bind" and item.get("Source") == self.workspace_source]
            if (len(workspace_mounts) != 1 or workspace_mounts[0].get("Destination") != "/workspace"
                    or workspace_mounts[0].get("RW") is not False):
                raise ProbeFailure("workspace_development_reader_mount_unconfirmed")
            readers.append(RegisteredWorkspaceReader(container_id=self.containers[role],
                operation_id=self.operation_id, scope=self.scope_id, method=METHOD,
                mount_destination="/workspace"))
        return tuple(readers)

    @staticmethod
    def discover_owned(environment_id: str, scope_id: str, *, operation_id: str | None = None) -> tuple[dict, ...]:
        """Inspect only containers with this fixed method and Workspace identity."""
        if not re.fullmatch(r"dev-env-[0-9a-f]{32}", environment_id) or not isinstance(scope_id, str):
            raise ProbeFailure("workspace_development_discovery_identity_invalid")
        filters = ["cloudhelm.method=" + METHOD, "cloudhelm.environment_id=" + environment_id,
                   "cloudhelm.scope=" + scope_id]
        if operation_id is not None:
            filters.append("cloudhelm.operation_id=" + operation_id)
        path = "/containers/json?all=1&filters=" + quote(
            json.dumps({"label": filters}, separators=(",", ":")), safe="")
        values = engine("GET", path)
        found, roles = [], set()
        for item in values:
            identity = item.get("Id", "")
            labels = item.get("Labels") or {}
            role = labels.get("cloudhelm.role")
            if (not re.fullmatch(r"[0-9a-f]{64}", identity) or role not in {"postgres", "backend", "migration"}
                    or role in roles or labels.get("cloudhelm.method") != METHOD
                    or labels.get("cloudhelm.environment_id") != environment_id
                    or labels.get("cloudhelm.scope") != scope_id
                    or (operation_id is not None and labels.get("cloudhelm.operation_id") != operation_id)):
                raise ProbeFailure("workspace_development_discovery_inventory_mismatch")
            actual = engine("GET", "/containers/" + identity + "/json")
            config_labels = actual.get("Config", {}).get("Labels") or {}
            if any(config_labels.get(key) != labels.get(key) for key in (
                    "cloudhelm.method", "cloudhelm.environment_id", "cloudhelm.scope",
                    "cloudhelm.operation_id", "cloudhelm.role")):
                raise ProbeFailure("workspace_development_discovery_identity_changed")
            mounts = tuple({"type": mount.get("Type"), "source": mount.get("Source"),
                            "destination": mount.get("Destination"), "readonly": mount.get("RW") is False}
                           for mount in actual.get("Mounts", []))
            roles.add(role)
            found.append({"container_id": identity, "role": role,
                          "operation_id": labels["cloudhelm.operation_id"],
                          "status": actual.get("State", {}).get("Status"),
                          "process_id": actual.get("State", {}).get("Pid"),
                          "paused": actual.get("State", {}).get("Paused") is True,
                          "restarting": actual.get("State", {}).get("Restarting") is True,
                          "running": actual.get("State", {}).get("Running") is True,
                          "mounts": mounts})
        return tuple(sorted(found, key=lambda item: item["role"]))


def _bootstrap(action: str) -> str:
    if action not in {"serve", MIGRATION_REVISION}:
        raise ProbeFailure("workspace_development_bootstrap_action_invalid")
    import json

    argv = (["/environment/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
             "--port", "8000", "--reload", "--reload-dir", "/workspace/backend/app"]
            if action == "serve" else
            ["/environment/bin/python", "-m", "alembic", "upgrade", MIGRATION_REVISION])
    # This is fixed code. The archive digest and size are supplied as non-secret data.
    return """import hashlib, os, pathlib, posixpath, re, stat, sys, tarfile
archive_name=os.environ.get('WORKSPACE_SNAPSHOT_FILE','')
if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', archive_name): raise SystemExit(80)
archive='/workspace-cache/'+archive_name
expected=os.environ.get('WORKSPACE_SNAPSHOT_SHA256','')
if not re.fullmatch(r'[0-9a-f]{64}', expected): raise SystemExit(81)
if os.stat(archive).st_size > 402653184: raise SystemExit(82)
h=hashlib.sha256()
with open(archive,'rb') as f:
 while True:
  b=f.read(1048576)
  if not b: break
  h.update(b)
if h.hexdigest()!=expected: raise SystemExit(83)
root=pathlib.Path('/environment')
members=[]; names=set(); total=0
with tarfile.open(archive,'r:*') as t:
 for m in t:
  if len(members)>=100000: raise SystemExit(84)
  n=m.name.rstrip('/')
  p=pathlib.PurePosixPath(n)
  if (not n or p.is_absolute() or any(x in ('','.','..') for x in n.split('/'))
      or len(n)>1024 or n in names): raise SystemExit(85)
  names.add(n)
  if m.isdir(): kind='dir'
  elif m.isfile():
   if m.mode & 0o7000 or m.mode & ~0o755 or (m.mode & 0o111 not in (0,0o111)): raise SystemExit(86)
   total+=m.size
   if total>536870912: raise SystemExit(87)
   kind='file'
  elif m.issym():
   target=m.linkname
   if not target or len(target)>1024: raise SystemExit(88)
   if target.startswith('/'):
    if target not in ('/usr/local/bin/python','/usr/local/bin/python3','/usr/local/bin/python3.12'): raise SystemExit(89)
   else:
    resolved=posixpath.normpath(posixpath.join(posixpath.dirname(n),target))
    if resolved in ('..','.') or resolved.startswith('../') or resolved.startswith('/'): raise SystemExit(90)
   kind='link'
  else: raise SystemExit(91)
  members.append((m,n,kind))
if not names: raise SystemExit(92)
kind_by_name={n:k for _,n,k in members}
for _,n,kind in members:
 for parent in pathlib.PurePosixPath(n).parents:
  if str(parent)=='.': break
  if str(parent) in kind_by_name and kind_by_name[str(parent)]!='dir': raise SystemExit(93)
 if kind=='link' and any(other.startswith(n+'/') for _,other,_ in members): raise SystemExit(94)
if any(root.iterdir()): raise SystemExit(95)
for m,n,kind in sorted(members,key=lambda x:(x[2]!='dir',x[1])):
 dest=root.joinpath(*n.split('/'))
 if kind=='dir':
  dest.mkdir(mode=0o755,parents=True,exist_ok=True)
  if not stat.S_ISDIR(dest.lstat().st_mode): raise SystemExit(96)
 elif kind=='file':
  dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
  cur=root
  for part in pathlib.PurePosixPath(n).parts[:-1]:
   cur=cur/part
   if not stat.S_ISDIR(cur.lstat().st_mode): raise SystemExit(97)
  src=t.extractfile(m)
  with open(dest,'xb') as out:
   while True:
    b=src.read(65536)
    if not b: break
    out.write(b)
  os.chmod(dest,0o755 if m.mode & 0o111 else 0o644)
for m,n,kind in members:
 if kind!='link': continue
 dest=root.joinpath(*n.split('/'))
 dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
 target=m.linkname
 if target.startswith('/'):
  allowed={'bin/python':'/usr/local/bin/python','bin/python3':'/usr/local/bin/python3','bin/python3.12':'/usr/local/bin/python3.12'}
  if allowed.get(n)!=target: raise SystemExit(98)
 os.symlink(target,dest)
os.execv('/environment/bin/python', """ + json.dumps(argv) + ")"""
