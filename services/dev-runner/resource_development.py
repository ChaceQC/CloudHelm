"""A fixed engineering envelope including its private Docker daemon and content store."""

import os
import stat
import time
from pathlib import Path

from packages.contracts.p0.resource_contracts import ResourceAllocation, ResourceVector
from packages.contracts.p1.resource_protocol import (
    DEVELOPMENT_BACKEND, ExecutorReceipt, RunnerRegistration, allocation_from_receipt, canonical_digest,
)
from . import development_storage as storage
from .artifact_environment_docker import command, engine
from modules.execution.docker_endpoint import use_socket
from .resource_limits import DockerScratchBoundary
from .resource_storage import observe_backing

RUNTIME_BYTES = 16 * 1024**2
ENVELOPE = ResourceVector(memory_mib=4096, cpu_millicores=3000, pids=512,
                          disk_bytes=4 * 1024**3 + RUNTIME_BYTES, heavy_slots=1)


def development_recipe(reference, owner):
    return canonical_digest({"backend": DEVELOPMENT_BACKEND, "storage": reference.model_dump(mode="json"),
                             "storage_owner": owner, "docker_storage": "containerd-overlayfs",
                             "limits": ENVELOPE.model_dump()})


def runtime_directory(binding):
    return Path("/run") / ("cloudhelm-engine-" + binding[9:41])


class DevelopmentBoundary(DockerScratchBoundary):
    backend = DEVELOPMENT_BACKEND

    def __init__(self, registration, ledger):
        self.registration, self.ledger = registration, ledger
        if development_recipe(registration.storage, registration.storage_owner_reservation_id) != registration.recipe_digest:
            raise ValueError("resource_development_recipe_mismatch")

    def _service(self, request):
        return "cloudhelmengine" + self.binding(request)[9:] + ".service"

    def _containerd_service(self, request):
        return "cloudhelmcontainerd" + self.binding(request)[9:] + ".service"

    def socket(self, request):
        return runtime_directory(self.binding(request)) / "docker.sock"

    def _data(self):
        return storage.ROOT / self.registration.storage.storage_id / "data/cache/managed-docker-r1"

    def _start_service(self, name, request, argv):
        command(["/usr/bin/busctl", "--", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
            name, "fail", "11", "Description", "s", self.binding(request),
            "Slice", "s", self._unit(request), "KillMode", "s", "control-group",
            "StandardOutput", "s", "null", "StandardError", "s", "null",
            "ExecStart", "a(sasb)", "1", argv[0], str(len(argv)), *argv, "false",
            "CPUQuotaPerSecUSec", "t", str(request.hard_limits.cpu_millicores * 1000),
            "CPUQuotaPeriodUSec", "t", str(request.identity.cpu_period_us),
            "MemoryMax", "t", str(request.hard_limits.memory_mib * 1024**2),
            "MemorySwapMax", "t", "0", "TasksMax", "t", str(request.hard_limits.pids), "0"])

    def _stop_service(self, name, request):
        result = command(["/usr/bin/systemctl", "show", name,
                          "--property=Description,LoadState,MainPID"], required=False)
        properties = dict(line.split("=", 1) for line in result.stdout.decode("utf-8").splitlines() if "=" in line)
        absent = properties.get("LoadState") == "not-found" and properties.get("MainPID") == "0"
        if not absent and properties.get("Description") != self.binding(request):
            raise ValueError("resource_development_service_identity_mismatch")
        if not absent:
            command(["/usr/bin/systemctl", "stop", name])

    def check_capability(self, request):
        if (request.hard_limits != ENVELOPE or request.accounted_vector != ENVELOPE
                or request.identity.resource_group_digest != self.registration.recipe_digest
                or request.identity.cpu_period_us != 100000):
            raise ValueError("resource_development_fixed_envelope_required")
        available = next(line.split()[1] for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
                         if line.startswith("MemAvailable:"))
        if int(available) < (ENVELOPE.memory_mib + 128) * 1024 or len(os.sched_getaffinity(0)) * 1000 < ENVELOPE.cpu_millicores:
            raise ValueError("resource_current_physical_headroom_insufficient")
        backing = observe_backing(self.registration.storage, mounted=True)
        if not backing.managed_docker:
            raise ValueError("resource_development_requires_managed_storage_r3")
        with self.ledger.locked() as db:
            stored = self.ledger.read(db, self.registration.storage_owner_reservation_id)
            if stored is None:
                raise ValueError("resource_development_storage_owner_missing")
            from packages.contracts.p0.resource_contracts import ResourceRequest

            owner = ResourceRequest.model_validate(stored[0])
            configuration = db.execute("SELECT value FROM configuration WHERE key=?",
                                       ("runner:" + owner.identity.executor_instance_id,)).fetchone()
            if configuration is None or RunnerRegistration.model_validate_json(configuration[0]).storage != self.registration.storage:
                raise ValueError("resource_development_storage_owner_binding_mismatch")
            receipt = ExecutorReceipt.model_validate(stored[1])
            allocation = allocation_from_receipt(ResourceAllocation(identity=owner.identity,
                creation_request_digest=owner.request_digest, allocation_revision=1, state="reserved",
                accounted_vector=owner.accounted_vector, hard_limits=owner.hard_limits), receipt)
            if (owner.identity.host_resource_pool_id != request.identity.host_resource_pool_id
                    or allocation.accounted_vector.disk_bytes != backing.backing_file_bytes
                    or receipt.state not in {"running", "stopped"}):
                raise ValueError("resource_development_storage_owner_unsettled")
        # Legacy daemon workloads are outside this envelope. Unknown old writers
        # must be reconciled before any new managed daemon can be started.
        with use_socket("/var/run/docker.sock"):
            legacy = engine("GET", "/containers/json?all=1")
        if any(any(key.startswith("cloudhelm.") for key in (item.get("Labels") or {})) for item in legacy):
            raise ValueError("resource_legacy_execution_requires_reconciliation")

    def _runtime(self, request):
        path = runtime_directory(self.binding(request))
        state = path.lstat()
        if not stat.S_ISDIR(state.st_mode) or state.st_uid != 0 or state.st_mode & 0o027:
            raise ValueError("resource_development_runtime_identity_mismatch")
        return path

    def start(self, request):
        self.check_capability(request)
        if os.geteuid() != 0:
            raise ValueError("resource_privileged_controller_required")
        if self._group(request).exists():
            raise ValueError("resource_existing_group_requires_reconciliation")
        runtime = runtime_directory(self.binding(request))
        runtime.mkdir(mode=0o750)
        os.chown(runtime, 0, storage.UID)
        command(["/usr/bin/mount", "-t", "tmpfs", "-o",
                 f"size={RUNTIME_BYTES},mode=0750,uid=0,gid={storage.UID},nosuid,nodev", "tmpfs", str(runtime)])
        data = self._data()
        data.mkdir(mode=0o700, exist_ok=True)
        state = data.lstat()
        parent = data.parent.stat()
        if (not stat.S_ISDIR(state.st_mode) or state.st_uid != 0 or state.st_dev != parent.st_dev
                or state.st_mode & 0o022):
            raise ValueError("resource_development_data_root_invalid")
        config = runtime / "daemon.json"
        descriptor = os.open(config, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, b"{}")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        containerd_config = runtime / "containerd.toml"
        descriptor = os.open(containerd_config, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, b'version = 3\ndisabled_plugins = ["io.containerd.grpc.v1.cri", "io.containerd.cri.v1.images", "io.containerd.cri.v1.runtime"]\n')
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        containerd_socket = runtime / "containerd.sock"
        self._start_service(self._containerd_service(request), request,
            ["/usr/bin/containerd", "--config", str(containerd_config), "--root", str(data / "containerd"),
             "--state", str(runtime / "containerd"), "--address", str(containerd_socket), "--log-level", "error"])
        # containerd is capped from its first process and holds the parent
        # alive while the aggregate cap is installed, before Docker starts.
        command(["/usr/bin/busctl", "--", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager", "SetUnitProperties", "sba(sv)", self._unit(request), "true", "6",
            "Description", "s", "CloudHelm resource " + self.binding(request),
            "CPUQuotaPerSecUSec", "t", str(request.hard_limits.cpu_millicores * 1000),
            "CPUQuotaPeriodUSec", "t", str(request.identity.cpu_period_us),
            "MemoryMax", "t", str(request.hard_limits.memory_mib * 1024**2),
            "MemorySwapMax", "t", "0", "TasksMax", "t", str(request.hard_limits.pids)])
        for _ in range(100):
            if containerd_socket.is_socket():
                break
            time.sleep(0.05)
        else:
            raise ValueError("resource_development_containerd_start_unconfirmed")
        argv = ["/usr/bin/dockerd", "--config-file=" + str(config), "--data-root=" + str(data),
                "--exec-root=" + str(runtime / "exec"), "--pidfile=" + str(runtime / "daemon.pid"),
                "--host=unix://" + str(self.socket(request)), "--group=cloudhelm",
                "--storage-driver=overlayfs", "--feature=containerd-snapshotter=true",
                "--containerd=" + str(containerd_socket), "--containerd-namespace=cloudhelm-development",
                "--containerd-plugins-namespace=cloudhelm-development-plugins",
                "--bridge=none", "--iptables=false", "--ip6tables=false", "--ip-forward=false",
                "--cgroup-parent=" + self._unit(request)]
        self._start_service(self._service(request), request, argv)
        for _ in range(100):
            try:
                state, _, evidence = self.observe(request)
                if state == "running":
                    return evidence
            except Exception:
                pass
            time.sleep(0.1)
        raise ValueError("resource_development_daemon_start_unconfirmed")

    def observe(self, request):
        observed = self._observe_group(request)
        runtime = self._runtime(request)
        values = os.statvfs(runtime)
        if values.f_blocks * values.f_frsize != RUNTIME_BYTES:
            raise ValueError("resource_development_runtime_not_bounded")
        with use_socket(self.socket(request)):
            info = engine("GET", "/info")
            containers = engine("GET", "/containers/json?all=1")
            if (info.get("DockerRootDir") != str(self._data()) or info.get("Driver") != "overlayfs"
                    or info.get("CgroupDriver") != "systemd" or info.get("CgroupVersion") != "2"):
                raise ValueError("resource_development_daemon_boundary_mismatch")
            for item in containers:
                value = engine("GET", "/containers/" + item["Id"] + "/json")
                state = value["State"]
                can_execute = (state["Running"] or state["Pid"] != 0
                               or value["HostConfig"]["RestartPolicy"]["Name"] not in {"", "no"})
                if can_execute and value["HostConfig"]["CgroupParent"] != self._unit(request):
                    raise ValueError("resource_development_child_outside_envelope")
        pids = []
        for name in (self._service(request), self._containerd_service(request)):
            result = command(["/usr/bin/systemctl", "show", name, "--property=MainPID", "--value"])
            pid = int(result.stdout.decode("utf-8").strip())
            lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
            if not any(line.startswith("0::/" + self._unit(request) + "/") for line in lines):
                raise ValueError("resource_development_daemon_outside_envelope")
            pids.append(pid)
        observe_backing(self.registration.storage, mounted=True)
        return "running", False, {**observed, "daemon_pid": pids[0], "containerd_pid": pids[1], "docker_content_bounded": True,
                                   "storage_owner": self.registration.storage_owner_reservation_id}

    def stop(self, request):
        # Identity and ownership must be checked before signalling any process.
        self._stop_service(self._service(request), request)
        self._stop_service(self._containerd_service(request), request)
        group = self._group(request)
        if group.exists():
            description = command(["/usr/bin/systemctl", "show", self._unit(request), "--property=Description", "--value"])
            if description.stdout.decode("utf-8").strip() != "CloudHelm resource " + self.binding(request):
                raise ValueError("resource_development_parent_identity_mismatch")
            if "populated 1" in (group / "cgroup.events").read_text(encoding="utf-8").splitlines():
                (group / "cgroup.kill").write_text("1", encoding="utf-8")
                for _ in range(100):
                    if "populated 0" in (group / "cgroup.events").read_text(encoding="utf-8").splitlines():
                        break
                    time.sleep(0.02)
            if "populated 0" not in (group / "cgroup.events").read_text(encoding="utf-8").splitlines():
                raise ValueError("resource_development_group_stop_unconfirmed")
            command(["/usr/bin/systemctl", "stop", self._unit(request)])
        from .resource_network import release

        release(self.binding(request))
        runtime = runtime_directory(self.binding(request))
        if runtime.exists():
            self._runtime(request)
            if os.path.ismount(runtime):
                command(["/usr/bin/umount", "--", str(runtime)])
            runtime.rmdir()  # An unexpected non-mount with contents is rejected.
        if self._group(request).exists() or runtime.exists():
            raise ValueError("resource_development_cleanup_unconfirmed")
        return True, {"process_group_removed": True, "runtime_tmpfs_reclaimed": True,
                      "disk_remaining_bytes": 0, "backing_owner_retained": True}
