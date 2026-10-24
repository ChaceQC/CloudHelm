"""A real, closed Linux execution boundary, with no image pulls or host writers.

Trusted infrastructure provisions the Runner and its recipe. Workloads run as
65534 in a read-only, disconnected container below a whole-group cgroup v2 cap.
Only /work and /dev/shm are writable, both bounded tmpfs charged to this group.
"""

import os
from pathlib import Path

from packages.contracts.p1.resource_protocol import BACKEND, canonical_digest
from .artifact_environment_docker import command, engine

SHM_BYTES = 1024 * 1024
LABEL = "cloudhelm.resource-binding"


def recipe_digest(image_id, argv):
    return canonical_digest({"backend": BACKEND, "image_id": image_id, "argv": list(argv)})


class DockerScratchBoundary:
    backend = BACKEND

    def __init__(self, registration, argv):
        self.registration, self.argv = registration, tuple(argv)
        if (not 1 <= len(self.argv) <= 64 or sum(len(a.encode("utf-8")) for a in self.argv) > 16384
                or recipe_digest(registration.image_id, self.argv) != registration.recipe_digest):
            raise ValueError("resource_recipe_registration_mismatch")

    def binding(self, request):
        return "resource-" + canonical_digest({"identity": request.identity.model_dump(mode="json"),
                                              "digest": request.request_digest})[7:47]

    def _unit(self, request):
        return "cloudhelmresource" + self.binding(request)[9:] + ".slice"

    def _group(self, request):
        return Path("/sys/fs/cgroup") / self._unit(request)

    def check_capability(self, request):
        if request.identity.resource_group_digest != self.registration.recipe_digest:
            raise ValueError("resource_recipe_digest_mismatch")
        if request.hard_limits.cpu_millicores * request.identity.cpu_period_us % 1000:
            raise ValueError("resource_cpu_quota_not_exactly_representable")
        memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines())
        available_kib = int(memory["MemAvailable"].split()[0])
        if (available_kib < (request.hard_limits.memory_mib + 128) * 1024
                or len(os.sched_getaffinity(0)) * 1000 < request.hard_limits.cpu_millicores):
            raise ValueError("resource_current_physical_headroom_insufficient")
        info = engine("GET", "/info")
        if info.get("CgroupDriver") != "systemd" or info.get("CgroupVersion") != "2":
            raise ValueError("resource_systemd_cgroup2_required")
        image = engine("GET", "/images/" + self.registration.image_id + "/json")
        if (image["Id"] != self.registration.image_id or image["Os"] != "linux"
                or image["Architecture"] != "amd64" or image["Config"].get("Volumes")):
            raise ValueError("resource_preloaded_image_capability_mismatch")

    def _expected(self, request):
        limits, period = request.hard_limits, request.identity.cpu_period_us
        return {"cpu.max": f"{limits.cpu_millicores * period // 1000} {period}",
                "memory.max": str(limits.memory_mib * 1024**2), "memory.swap.max": "0",
                "pids.max": str(limits.pids)}

    def prepare_group(self, request):
        group = self._group(request)
        if group.exists():
            raise ValueError("resource_existing_group_requires_reconciliation")
        if os.geteuid() != 0:
            raise ValueError("resource_privileged_group_controller_required")
        limits = request.hard_limits
        command(["/usr/bin/busctl", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
            self._unit(request), "fail", "6", "Description", "s", "CloudHelm resource " + self.binding(request),
            "CPUQuotaPerSecUSec", "t", str(limits.cpu_millicores * 1000),
            "CPUQuotaPeriodUSec", "t", str(request.identity.cpu_period_us),
            "MemoryMax", "t", str(limits.memory_mib * 1024**2), "MemorySwapMax", "t", "0",
            "TasksMax", "t", str(limits.pids), "0"])
        self._observe_group(request)

    def _observe_group(self, request):
        group = self._group(request)
        observed = {name: (group / name).read_text(encoding="utf-8").strip() for name in self._expected(request)}
        if observed != self._expected(request):
            raise ValueError("resource_group_kernel_limits_mismatch")
        return observed

    def _container(self, request):
        binding = self.binding(request)
        values = engine("GET", '/containers/json?all=1&filters={"label":["' + LABEL + '=' + binding + '"]}')
        if not values:
            return None
        if len(values) != 1:
            raise ValueError("resource_process_binding_ambiguous")
        value = engine("GET", "/containers/" + values[0]["Id"] + "/json")
        labels = value["Config"].get("Labels") or {}
        if (labels.get(LABEL) != binding or value["Name"] != "/" + binding
                or labels.get("cloudhelm.reservation") != request.identity.reservation_id):
            raise ValueError("resource_process_binding_mismatch")
        return value

    def start(self, request):
        self.prepare_group(request)
        limits, period = request.hard_limits, request.identity.cpu_period_us
        work_bytes = limits.disk_bytes - SHM_BYTES
        payload = {
            "Image": self.registration.image_id, "Cmd": list(self.argv), "Entrypoint": [],
            "User": "65534:65534", "WorkingDir": "/work", "Env": ["PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/work"],
            "Labels": {LABEL: self.binding(request), "cloudhelm.reservation": request.identity.reservation_id},
            "HostConfig": {
                "ReadonlyRootfs": True, "NetworkMode": "none", "IpcMode": "private", "ShmSize": SHM_BYTES,
                "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"], "LogConfig": {"Type": "none"},
                "CgroupParent": self._unit(request), "Memory": limits.memory_mib * 1024**2,
                "MemorySwap": limits.memory_mib * 1024**2, "PidsLimit": limits.pids,
                "CpuQuota": limits.cpu_millicores * period // 1000, "CpuPeriod": period,
                "Tmpfs": {"/work": f"rw,nosuid,nodev,noexec,size={work_bytes},mode=1777"},
            },
        }
        created = engine("POST", "/containers/create?name=" + self.binding(request), payload)
        engine("POST", "/containers/" + created["Id"] + "/start")
        state, _, evidence = self.observe(request)
        if state != "running":
            raise ValueError("resource_physical_start_unconfirmed")
        return evidence

    def observe(self, request):
        container = self._container(request)
        if container is None:
            # Absence after an uncertain create is not a durable no-start fence.
            return "unknown", False, {"container_absent_requires_reconciliation": True}
        host = container["HostConfig"]
        if (not host["ReadonlyRootfs"] or host["NetworkMode"] != "none" or host["Privileged"]
                or host.get("Binds") or host.get("Devices") or host.get("CapAdd")
                or host["CgroupParent"] != self._unit(request) or container["Config"]["User"] != "65534:65534"
                or set(host.get("Tmpfs", {})) != {"/work"}
                or host["ShmSize"] != SHM_BYTES or host["LogConfig"]["Type"] != "none"
                or container["Config"]["Image"] != self.registration.image_id):
            raise ValueError("resource_container_boundary_mismatch")
        if any(mount["Type"] != "tmpfs" or mount["Destination"] != "/work" for mount in container["Mounts"]):
            raise ValueError("resource_unaccounted_writable_mount")
        observed = self._observe_group(request)
        if not container["State"]["Running"]:
            return "stopped", False, {"process_stopped": True, "disk_cleanup_pending": True}
        pid = container["State"]["Pid"]
        lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        relative = next((line[3:] for line in lines if line.startswith("0::/")), "")
        process_group = Path("/sys/fs/cgroup") / relative.lstrip("/")
        if not relative or not process_group.is_relative_to(self._group(request)) or process_group == self._group(request):
            raise ValueError("resource_process_outside_group")
        return "running", False, {**observed, "pid": pid, "process_descends_from_group": True,
                                   "scratch_limit_bytes": request.hard_limits.disk_bytes, "readonly_root": True}

    def stop(self, request):
        container = self._container(request)
        if container is None:
            raise ValueError("resource_missing_process_requires_reconciliation")
        identity = container["Id"]
        engine("POST", "/containers/" + identity + "/stop?t=2", expected=(204, 304))
        stopped = engine("GET", "/containers/" + identity + "/json")
        if stopped["State"]["Running"] or stopped["State"]["Pid"]:
            raise ValueError("resource_process_stop_unconfirmed")
        engine("DELETE", "/containers/" + identity, expected=(204,))
        group = self._group(request)
        if group.exists():
            if "populated 0" not in (group / "cgroup.events").read_text(encoding="utf-8").splitlines():
                raise ValueError("resource_group_still_populated")
            command(["/usr/bin/systemctl", "stop", self._unit(request)])
        if self._container(request) is not None or group.exists():
            raise ValueError("resource_group_cleanup_unconfirmed")
        return True, {"process_group_removed": True, "container_removed": True, "tmpfs_reclaimed": True}
