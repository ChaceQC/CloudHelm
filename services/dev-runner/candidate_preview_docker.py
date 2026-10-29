"""The single fixed notes runtime; no caller-provided Docker options or targets."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from packages.contracts.p1.development_environment import DATA_REVISION, MIGRATION_REVISION

from .artifact_environment_docker import METHOD, docker, engine, stop as stop_container
from .candidate_preview_journal import read, write
from .toolchain import DockerClient, ProbeFailure
from .workspace_development_recipe import DATABASE_SQL_COMMAND, data_statements

LIMITS = {"postgres": (256 * 1024**2, 50000, 64), "backend": (512 * 1024**2, 75000, 128),
          "frontend": (128 * 1024**2, 25000, 64)}
TMPFS = {"postgres": {"/tmp": 16 * 1024**2, "/var/run/postgresql": 4 * 1024**2},
         "backend": {"/tmp": 16 * 1024**2},
         "frontend": {"/tmp": 8 * 1024**2, "/var/cache/nginx": 16 * 1024**2, "/var/run": 1024**2}}
ROLES = ("postgres", "migration", "backend", "frontend")


class CandidatePreviewDocker:
    def __init__(self, operation_id, binding_digest, group, directory, artifacts):
        self.operation_id, self.binding_digest, self.group = operation_id, binding_digest, group
        self.directory, self.artifacts = directory, artifacts
        self.name = "candidate-preview-" + hashlib.sha256(operation_id.encode()).hexdigest()[:32]
        self.labels = {"cloudhelm.method": METHOD, "cloudhelm.operation_id": operation_id,
                       "cloudhelm.scope": "p2-fixed-candidate-preview", "cloudhelm.input_binding": binding_digest}
        self.network_id = None
        self.containers = {}

    def _secret(self, name, value):
        descriptor = os.open(self.directory / "secrets" / name,
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

    def _discover(self):
        filters = quote(json.dumps({"label": ["cloudhelm.method=" + METHOD,
            "cloudhelm.operation_id=" + self.operation_id]}, separators=(",", ":")), safe="")
        networks = engine("GET", "/networks?filters=" + filters)
        if len(networks) > 1:
            raise ProbeFailure("candidate_preview_duplicate_network")
        self.network_id = None
        if networks:
            identity = networks[0].get("Id", "")
            if not re.fullmatch(r"[0-9a-f]{64}", identity):
                raise ProbeFailure("candidate_preview_network_identity_invalid")
            network = engine("GET", "/networks/" + identity)
            labels = network.get("Labels") or {}
            if (network.get("Name") != self.name or network.get("Driver") != "bridge"
                    or network.get("Internal") is not True
                    or labels.get("cloudhelm.resource-binding") != self.group.binding
                    or any(labels.get(key) != value for key, value in self.labels.items())):
                raise ProbeFailure("candidate_preview_network_identity_mismatch")
            self.network_id = identity
        self.containers = {}
        values = engine("GET", "/containers/json?all=1&filters=" + filters)
        for item in values:
            identity, labels = item.get("Id", ""), item.get("Labels") or {}
            role = labels.get("cloudhelm.role")
            if (not re.fullmatch(r"[0-9a-f]{64}", identity) or role not in ROLES or role in self.containers
                    or any(labels.get(key) != value for key, value in self.labels.items())):
                raise ProbeFailure("candidate_preview_container_identity_conflict")
            actual = engine("GET", "/containers/" + identity + "/json")
            if any((actual["Config"].get("Labels") or {}).get(key) != value
                   for key, value in (self.labels | {"cloudhelm.role": role}).items()):
                raise ProbeFailure("candidate_preview_container_identity_changed")
            self.containers[role] = identity

    def _configuration(self, role, owner_password, app_password):
        actual_role = "backend" if role == "migration" else role
        memory, cpu, pids = LIMITS[actual_role]
        host = {"ReadonlyRootfs": True, "NetworkMode": self.network_id, "CgroupParent": self.group.unit,
                "Memory": memory, "MemorySwap": memory, "CpuPeriod": 100000, "CpuQuota": cpu,
                "PidsLimit": pids, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                "IpcMode": "private", "ShmSize": 64 * 1024**2 if role == "postgres" else 1024**2,
                "LogConfig": {"Type": "none", "Config": {}}, "RestartPolicy": {"Name": "no"},
                "DnsOptions": ["timeout:1", "attempts:1"],
                "Tmpfs": {path: f"rw,nosuid,nodev,noexec,size={size},uid=1000,gid=1000,mode=1777"
                          for path, size in TMPFS[actual_role].items()}}
        config = {"Image": self.artifacts[actual_role].manifest_digest,
                  "User": "1000:1000" if role == "postgres" else "0:0",
                  "Labels": self.labels | {"cloudhelm.role": role}, "HostConfig": host,
                  "NetworkingConfig": {"EndpointsConfig": {self.network_id: {"Aliases": [role]}}}}
        if role == "postgres":
            host["Mounts"] = [{"Type": "bind", "Source": str(self.directory / "database"),
                               "Target": "/var/lib/postgresql/data", "ReadOnly": False},
                              {"Type": "bind", "Source": str(self.directory / "secrets"),
                               "Target": "/run/cloudhelm-secrets", "ReadOnly": True}]
            config["Env"] = ["POSTGRES_DB=reference_notes", "POSTGRES_USER=reference_owner",
                "POSTGRES_PASSWORD_FILE=/run/cloudhelm-secrets/owner",
                "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=scram-sha-256"]
            config["Cmd"] = ["postgres", "-c", "max_connections=30", "-c", "shared_buffers=32MB",
                             "-c", "log_min_messages=panic", "-c", "log_statement=none"]
        elif actual_role == "backend":
            username, password = ("reference_owner", owner_password) if role == "migration" else ("reference_app", app_password)
            config["Env"] = [f"DATABASE_URL=postgresql+psycopg://{username}:{password}@postgres:5432/reference_notes",
                             "PYTHONDONTWRITEBYTECODE=1"]
            if role == "migration":
                config["Entrypoint"], config["Cmd"] = ["alembic"], ["upgrade", MIGRATION_REVISION]
        else:
            host["CapAdd"] = ["SETUID", "SETGID", "CHOWN"]
            config["ExposedPorts"] = {"80/tcp": {}}
        return config

    def _create_start(self, role, owner_password, app_password, client, gate):
        gate()
        journal = read(self.directory / "execution.json")
        if journal.get("binding_digest") != self.binding_digest or role in journal["attempted_roles"]:
            raise ProbeFailure("candidate_preview_launch_identity_conflict")
        journal["attempted_roles"].append(role)
        write(self.directory / "execution.json", journal)
        value = engine("POST", "/containers/create?name=" + self.name + "-" + role,
                       self._configuration(role, owner_password, app_password))
        self.containers[role] = value["Id"]
        gate()
        client.run("start", value["Id"])

    def _sql(self, statement, *, required=True):
        return docker("exec", "--env=PGPASSFILE=/run/cloudhelm-secrets/owner.pgpass", "-i",
                      self.containers["postgres"], *DATABASE_SQL_COMMAND,
                      input_bytes=statement.encode("utf-8"), required=required)

    def prepare(self, gate):
        gate()
        (self.directory / "database").mkdir(mode=0o700)
        (self.directory / "secrets").mkdir(mode=0o700)
        owner_password, app_password = secrets.token_hex(32), secrets.token_hex(32)
        self._secret("owner", owner_password)
        self._secret("owner.pgpass", "localhost:5432:reference_notes:reference_owner:" + owner_password + "\n")
        client = DockerClient.create(self.directory)
        gate()
        self.network_id = engine("POST", "/networks/create", {"Name": self.name, "Driver": "bridge",
            "Internal": True, "CheckDuplicate": True, "Labels": self.labels})["Id"]
        self._discover()
        if self.network_id is None:
            raise ProbeFailure("candidate_preview_network_start_unconfirmed")
        self._create_start("postgres", owner_password, app_password, client, gate)
        for _ in range(60):
            gate()
            query = self._sql("SELECT 1;", required=False)
            if query.returncode == 0 and query.stdout.strip() == b"1":
                break
            time.sleep(0.5)
        else:
            raise ProbeFailure("candidate_preview_database_not_ready")
        self._create_start("migration", owner_password, app_password, client, gate)
        for _ in range(60):
            state = engine("GET", "/containers/" + self.containers["migration"] + "/json")["State"]
            if not state["Running"]:
                if state["ExitCode"] != 0 or state["Pid"] != 0:
                    raise ProbeFailure("candidate_preview_migration_failed")
                break
            gate()
            time.sleep(0.5)
        else:
            raise ProbeFailure("candidate_preview_migration_unconfirmed")
        gate()
        initialize, _, _, _ = data_statements(DATA_REVISION)
        self._sql(initialize.replace("{password}", app_password))
        for role in ("backend", "frontend"):
            self._create_start(role, owner_password, app_password, client, gate)

    def _inspect_running(self, role):
        identity = self.containers[role]
        value = engine("GET", "/containers/" + identity + "/json")
        state, host = value["State"], value["HostConfig"]
        memory, cpu, pids = LIMITS[role]
        caps = {"SETUID", "SETGID", "CHOWN"} if role == "frontend" else set()
        if (not state["Running"] or state["Pid"] <= 0 or state.get("Paused") or state.get("Restarting")
                or value["Image"] not in {self.artifacts[role].manifest_digest, self.artifacts[role].config_digest}
                or value["Config"]["Image"] != self.artifacts[role].manifest_digest
                or value["Config"]["User"] != ("1000:1000" if role == "postgres" else "0:0")
                or host["CgroupParent"] != self.group.unit or host["Memory"] != memory
                or host["MemorySwap"] != memory or host["CpuPeriod"] != 100000 or host["CpuQuota"] != cpu
                or host["PidsLimit"] != pids or host.get("Privileged") or not host["ReadonlyRootfs"]
                or set(host.get("CapDrop") or []) != {"ALL"}
                or {item.removeprefix("CAP_") for item in host.get("CapAdd") or []} != caps
                or host.get("Devices") or host.get("PortBindings") or host.get("PublishAllPorts")
                or host["NetworkMode"] != self.network_id or host["LogConfig"]["Type"] != "none"
                or host["RestartPolicy"]["Name"] != "no"):
            raise ProbeFailure("candidate_preview_container_boundary_mismatch")
        configured = self._configuration(role, "", "")["HostConfig"]
        if (host["Tmpfs"] != configured["Tmpfs"] or host["ShmSize"] != configured["ShmSize"]
                or host["IpcMode"] != "private" or host.get("SecurityOpt") != ["no-new-privileges:true"]):
            raise ProbeFailure("candidate_preview_runtime_isolation_mismatch")
        expected_mounts = {item["Target"]: (item["Source"], item["ReadOnly"])
                           for item in configured.get("Mounts", [])}
        binds = {item["Destination"]: (item["Source"], not item["RW"])
                 for item in value["Mounts"] if item["Type"] == "bind"}
        if (binds != expected_mounts or any(item["Type"] not in {"bind", "tmpfs"}
                or item["Type"] == "tmpfs" and item["Destination"] not in set(TMPFS[role]) | {"/dev/shm"}
                for item in value["Mounts"])):
            raise ProbeFailure("candidate_preview_mount_boundary_mismatch")
        lines = Path(f'/proc/{state["Pid"]}/cgroup').read_text(encoding="utf-8").splitlines()
        path = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/") for line in lines if line.startswith("0::/")), None)
        if path is None or not path.is_relative_to(self.group.path):
            raise ProbeFailure("candidate_preview_process_outside_group")
        expected = {"cpu.max": f"{cpu} 100000", "memory.max": str(memory),
                    "memory.swap.max": "0", "pids.max": str(pids)}
        if {name: (path / name).read_text(encoding="utf-8").strip() for name in expected} != expected:
            raise ProbeFailure("candidate_preview_child_limits_mismatch")
        if role == "postgres":
            for name, target in (("database", "/var/lib/postgresql/data"), ("secrets", "/run/cloudhelm-secrets")):
                actual = docker("exec", identity, "stat", "-c", "%d %i", target).stdout.split()
                source = (self.directory / name).stat(follow_symlinks=False)
                if actual != [str(source.st_dev).encode(), str(source.st_ino).encode()]:
                    raise ProbeFailure("candidate_preview_mount_inode_mismatch")
        endpoints = [item for item in value["NetworkSettings"]["Networks"].values()
                     if item["NetworkID"] == self.network_id]
        if len(endpoints) != 1:
            raise ProbeFailure("candidate_preview_endpoint_unconfirmed")
        address = ipaddress.ip_address(endpoints[0]["IPAddress"])
        if address.version != 4 or not address.is_private or address.is_loopback:
            raise ProbeFailure("candidate_preview_endpoint_invalid")
        return {"container_id": identity, "ipv4": str(address), "pid": state["Pid"]}

    def observe(self):
        self.group.observe()
        self._discover()
        if self.network_id is None or set(self.containers) != set(ROLES):
            return {"state": "preparing"}
        migration_value = engine("GET", "/containers/" + self.containers["migration"] + "/json")
        migration, host, config = migration_value["State"], migration_value["HostConfig"], migration_value["Config"]
        if (migration["Running"] or migration["Pid"] != 0 or migration["ExitCode"] != 0
                or migration_value["Image"] not in {self.artifacts["backend"].manifest_digest,
                                                     self.artifacts["backend"].config_digest}
                or config["Image"] != self.artifacts["backend"].manifest_digest
                or config["Entrypoint"] != ["alembic"] or config["Cmd"] != ["upgrade", MIGRATION_REVISION]
                or host["CgroupParent"] != self.group.unit or host["NetworkMode"] != self.network_id
                or host["Memory"] != LIMITS["backend"][0] or host["MemorySwap"] != LIMITS["backend"][0]
                or host["CpuQuota"] != LIMITS["backend"][1] or host["CpuPeriod"] != 100000
                or host["PidsLimit"] != LIMITS["backend"][2] or not host["ReadonlyRootfs"]
                or set(host.get("CapDrop") or []) != {"ALL"} or host.get("CapAdd")
                or host.get("Privileged") or host.get("PortBindings") or host.get("PublishAllPorts")):
            return {"state": "preparing"}
        facts = {role: self._inspect_running(role) for role in ("postgres", "backend", "frontend")}
        _, seed, _, security = data_statements(DATA_REVISION)
        for statement, expected in (("SELECT version_num FROM alembic_version;", MIGRATION_REVISION.encode()),
                                    (seed, b"1"), (security, b"t")):
            result = self._sql(statement, required=False)
            if result.returncode or result.stdout.strip() != expected:
                return {"state": "preparing"}
        for path, expected in (("/health", {"status": "ok"}), ("/ready", {"status": "ready"})):
            connection = http.client.HTTPConnection(facts["frontend"]["ipv4"], 80, timeout=2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                body = response.read(4097)
                if response.status != 200 or len(body) > 4096 or json.loads(body) != expected:
                    return {"state": "preparing"}
            except (OSError, ValueError, http.client.HTTPException):
                return {"state": "preparing"}
            finally:
                connection.close()
        connection = http.client.HTTPConnection(facts["frontend"]["ipv4"], 80, timeout=2)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            if (response.status != 200 or not response.getheader("Content-Type", "").startswith("text/html")
                    or not response.read(1)):
                return {"state": "preparing"}
        except (OSError, http.client.HTTPException):
            return {"state": "preparing"}
        finally:
            connection.close()
        return {"state": "ready", "data_revision": DATA_REVISION, "migration_revision": MIGRATION_REVISION,
                "containers": facts, "targets": {"frontend": {"ipv4": facts["frontend"]["ipv4"], "port": 80},
                                                    "backend": {"ipv4": facts["backend"]["ipv4"], "port": 8000}},
                "network_id": self.network_id, "host_ports_published": False}

    def wait_ready(self, gate):
        for _ in range(60):
            gate()
            result = self.observe()
            if result["state"] == "ready":
                return result
            time.sleep(0.5)
        raise ProbeFailure("candidate_preview_readiness_unconfirmed")

    def stop(self):
        self._discover()
        journal = read(self.directory / "execution.json")
        if (journal.get("binding_digest") != self.binding_digest
                or not set(journal.get("attempted_roles", ())).issubset(ROLES)
                or not set(journal.get("stop_facts", {})).issubset(ROLES)):
            raise ProbeFailure("candidate_preview_execution_journal_invalid")
        if set(journal["attempted_roles"]) - set(self.containers) - set(journal["stop_facts"]):
            raise ProbeFailure("candidate_preview_missing_container_requires_reconciliation")
        for role in ("frontend", "backend", "migration", "postgres"):
            if role not in self.containers:
                continue
            identity = self.containers[role]
            fact = stop_container(identity, self.operation_id) | {"role": role}
            if role in journal["stop_facts"] and journal["stop_facts"][role]["container_id"] != identity:
                raise ProbeFailure("candidate_preview_stop_identity_conflict")
            journal["stop_facts"][role] = fact
            write(self.directory / "execution.json", journal)
            engine("DELETE", "/containers/" + identity + "?v=1", expected=(204,))
        self._discover()
        if self.containers:
            raise ProbeFailure("candidate_preview_containers_remain")
        if self.network_id is not None:
            engine("DELETE", "/networks/" + self.network_id, expected=(204,))
        self._discover()
        if self.network_id is not None or self.containers:
            raise ProbeFailure("candidate_preview_cleanup_unconfirmed")
        return [journal["stop_facts"][role] for role in ROLES if role in journal["stop_facts"]]
