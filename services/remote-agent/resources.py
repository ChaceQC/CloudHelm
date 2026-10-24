"""Require a pre-admitted kernel group and a dedicated bounded Docker filesystem."""

import os
import subprocess
import re
from pathlib import Path

from .ledger import RemoteError


class Resources:
    def __init__(self, docker, *, mount_root, cgroup_path, cgroup_parent, daemon_pid_file):
        # These paths are maintenance inputs, never accepted through plan messages.
        self.docker = docker
        self.mount = Path(mount_root).resolve(strict=True)
        self.group = Path(cgroup_path).resolve(strict=True)
        self.parent = cgroup_parent
        self.daemon_pid_file = Path(daemon_pid_file)

    def authorize_network(self, network_id, namespace):
        if not re.fullmatch(r"[0-9a-f]{64}", network_id) or not re.fullmatch(r"ch-[0-9a-f]{32}", namespace):
            raise RemoteError("remote_network_identity_invalid")
        value = self.docker.api("GET", "/networks/" + network_id)
        if (not value.get("Internal") or value.get("Driver") != "bridge"
                or value.get("Labels", {}).get("cloudhelm.namespace") != namespace):
            raise RemoteError("remote_network_ownership_invalid")
        interface = "br-" + network_id[:12]
        index = int((Path("/sys/class/net") / interface / "ifindex").read_text(encoding="utf-8"))
        rule = ["-i", interface, "-o", interface, "-m", "comment", "--comment",
            "cloudhelm-remote:" + namespace + ":" + str(index), "-j", "ACCEPT"]
        result = subprocess.run(["/usr/sbin/iptables", "-w", "2", "-C", "FORWARD", *rule], capture_output=True)
        if result.returncode == 1:
            result = subprocess.run(["/usr/sbin/iptables", "-w", "2", "-I", "FORWARD", "1", *rule], capture_output=True)
        if result.returncode:
            raise RemoteError("remote_network_forwarding_unavailable")

    def verify(self, requested):
        if not self.mount.is_mount() or not self.group.is_relative_to(Path("/sys/fs/cgroup")):
            raise RemoteError("remote_dedicated_resource_boundary_required")
        disk = os.statvfs(self.mount)
        if disk.f_blocks * disk.f_frsize > requested.disk_bytes:
            raise RemoteError("remote_disk_hard_limit_exceeds_reservation")
        cpu = (self.group / "cpu.max").read_text(encoding="utf-8").strip().split()
        memory = (self.group / "memory.max").read_text(encoding="utf-8").strip()
        pids = (self.group / "pids.max").read_text(encoding="utf-8").strip()
        if (len(cpu) != 2 or cpu[0] == "max" or int(cpu[0]) * 1000 > requested.cpu_millicores * int(cpu[1])
                or memory == "max" or int(memory) > requested.memory_mib * 1024**2
                or pids == "max" or int(pids) > requested.pids):
            raise RemoteError("remote_kernel_limit_exceeds_reservation")
        info = self.docker.api("GET", "/info")
        if self.parent != self.group.name or not self.parent.endswith(".slice") or info["CgroupDriver"] != "systemd":
            raise RemoteError("remote_cgroup_parent_mismatch")
        if not Path(info["DockerRootDir"]).resolve().is_relative_to(self.mount):
            raise RemoteError("remote_docker_storage_outside_admitted_filesystem")
        # Agent and its child commands must already belong to the admitted group.
        membership = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        relative = str(self.group.relative_to("/sys/fs/cgroup"))
        expected_group = "0::/" + relative
        if not any(line == expected_group or line.startswith(expected_group + "/") for line in membership.splitlines()):
            raise RemoteError("remote_executor_outside_admitted_group")
        pid = int(self.daemon_pid_file.read_text(encoding="utf-8").strip())
        daemon_group = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
        if (Path(f"/proc/{pid}/exe").resolve().name != "dockerd" or not any(
                line == expected_group or line.startswith(expected_group + "/") for line in daemon_group.splitlines())):
            raise RemoteError("remote_daemon_outside_admitted_group")
        return {"cpu_max": " ".join(cpu), "memory_max": memory, "pids_max": pids,
            "filesystem_bytes": disk.f_blocks * disk.f_frsize, "available_bytes": disk.f_bavail * disk.f_frsize}
