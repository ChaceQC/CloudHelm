"""G01a read-only Linux snapshot; stdout is a UTF-8, allowlisted JSON summary.

Run with ``python3 topology_snapshot.py wsl`` or stream this file to an
already-authorized SSH connection and run ``python3 - s2413``. This collector
does not establish SSH connections, write files, query databases, inspect
container configuration, or grant resources. Profiles select candidate paths,
not host identity; the caller must verify the actual transport target.
"""

import argparse
import ipaddress
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


REVISION = "p0-topology-r2"
LIMIT = 262144
PATHS = {
    "wsl": ("/", "/mnt/e/Project/CloudHelm", "/var/lib/docker"),
    "s2413": ("/", "/srv/cloudhelm", "/var/lib/cloudhelm",
              "/var/log/cloudhelm", "/run/cloudhelm", "/var/lib/docker"),
}
QUOTA_FLAGS = {"quota", "usrquota", "grpquota", "prjquota", "pquota", "uquota", "gquota",
               "usrjquota", "grpjquota", "jqfmt", "noquota"}
CONTROLLERS = {"cpu", "cpuset", "memory", "pids", "io", "hugetlb", "rdma", "misc", "dmem"}
VERSIONS = {
    "git": ("git", "--version"), "uv": ("uv", "--version"),
    "node": ("node", "--version"), "npm": ("npm", "--version"),
    "rustc": ("rustc", "--version"), "cargo": ("cargo", "--version"),
    "docker_client": ("docker", "--version"),
    "compose": ("docker", "compose", "version", "--short"),
}


class ProbeFailure(Exception):
    def __init__(self, status, exit_code=None):
        self.status, self.exit_code = status, exit_code


def observe(probe, *args):
    """A failed probe cannot print stderr/secrets or suppress other sections."""
    try:
        return {"status": "observed", "value": probe(*args)}
    except ProbeFailure as error:
        return {"status": error.status, "exit_code": error.exit_code}
    except Exception as error:
        return {"status": "unknown", "error_type": type(error).__name__}


def read(path):
    with Path(path).open(encoding="utf-8") as stream:
        value = stream.read(LIMIT + 1)
    if len(value) > LIMIT:
        raise ProbeFailure("output_limit")
    return value.strip()


def command(*args):
    # No shell; no credentials/proxy/model variables are passed to children.
    executable = shutil.which(args[0])
    if executable is None:
        raise ProbeFailure("unavailable")
    parts = Path(executable).resolve().parts
    if len(parts) > 2 and parts[1] == "mnt" and re.fullmatch(r"[a-zA-Z]", parts[2]):
        raise ProbeFailure("windows_mounted_executable_not_run")
    environment = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    environment.update(LANG="C.UTF-8", LC_ALL="C.UTF-8")
    try:
        result = subprocess.run((executable, *args[1:]), capture_output=True, text=True, encoding="utf-8",
                                errors="strict", timeout=10, cwd="/", env=environment)
    except FileNotFoundError:
        raise ProbeFailure("unavailable") from None
    except subprocess.TimeoutExpired:
        raise ProbeFailure("timeout") from None
    if result.returncode:
        raise ProbeFailure("command_failed", result.returncode)
    if len(result.stdout) > LIMIT:
        raise ProbeFailure("output_limit")
    return result.stdout.strip()


def version(args):
    # Never return unparsed program output, even on a successful exit.
    match = re.search(r"\b(v?\d+\.\d+(?:\.\d+)?[a-zA-Z0-9.+~_-]{0,48})\b", command(*args))
    if not match:
        raise ProbeFailure("unrecognized_version")
    return match.group(1)


def system():
    values = {}
    for line in read("/etc/os-release").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ID", "VERSION_ID", "PRETTY_NAME", "VERSION_CODENAME"}:
            value = value.strip('"')
            if re.fullmatch(r"[A-Za-z0-9 ._()+/-]{1,120}", value):
                values[key] = value
    kernel, architecture = platform.release(), platform.machine()
    if not re.fullmatch(r"[A-Za-z0-9.+_-]{1,120}", kernel):
        raise ProbeFailure("kernel_format_unknown")
    if architecture not in {"x86_64", "aarch64", "armv7l", "i686", "riscv64", "ppc64le", "s390x"}:
        raise ProbeFailure("architecture_unknown")
    values.update(kernel=kernel, architecture=architecture,
                  python=platform.python_version(), logical_cpu_count=os.cpu_count(),
                  affinity_cpu_count=len(os.sched_getaffinity(0)),
                  effective_identity="root" if os.geteuid() == 0 else "nonroot",
                  ssh_session_present="SSH_CONNECTION" in os.environ)
    return values


def memory():
    selected = {"MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached", "SwapTotal", "SwapFree"}
    values = {}
    for line in read("/proc/meminfo").splitlines():
        key, _, value = line.partition(":")
        if key in selected:
            values[key + "_bytes"] = int(value.split()[0]) * 1024
    values["SwapUsed_bytes"] = values["SwapTotal_bytes"] - values["SwapFree_bytes"]
    return values


def load():
    values = read("/proc/loadavg").split()
    runnable, tasks = map(int, values[3].split("/"))
    return {"load_1_5_15_minutes": [float(value) for value in values[:3]],
            "runnable_tasks": runnable, "visible_tasks": tasks}


def mount_details(path):
    selected = None
    for line in read("/proc/self/mountinfo").splitlines():
        fields = line.split()
        separator = fields.index("-")
        mount = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4]))
        if path.is_relative_to(mount) and (selected is None or len(str(mount)) > selected[0]):
            flags = {value.split("=", 1)[0] for value in
                     fields[5].split(",") + fields[separator + 3].split(",")}
            selected = (len(str(mount)), {"filesystem_type": fields[separator + 1],
                        "mount_read_only": "ro" in flags,
                        "quota_mount_flags": sorted(flags & QUOTA_FLAGS)})
    if selected is None:
        raise ProbeFailure("mount_unknown")
    return selected[1]


def storage(path_text, devices):
    path = Path(path_text)
    # Refuse all symlinked candidate/ancestor paths; do not traverse their targets.
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        return {"path": path_text, "status": "symlink_not_followed"}
    exists = path.exists()
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    metadata, usage = ancestor.stat(), os.statvfs(ancestor)
    if metadata.st_dev not in devices:
        devices[metadata.st_dev] = "filesystem-" + str(len(devices) + 1)
    return {"path": path_text, "exists": exists, "observed_ancestor": str(ancestor),
            "directory": stat.S_ISDIR(metadata.st_mode) if exists else None,
            "mode": oct(stat.S_IMODE(metadata.st_mode)) if exists else None,
            "filesystem_ref": devices[metadata.st_dev], **mount_details(ancestor),
            "total_bytes": usage.f_blocks * usage.f_frsize,
            "used_bytes": (usage.f_blocks - usage.f_bfree) * usage.f_frsize,
            "available_bytes": usage.f_bavail * usage.f_frsize,
            "total_inodes": usage.f_files, "free_inodes": usage.f_favail,
            "inode_capacity_consistent": 0 <= usage.f_favail <= usage.f_files,
            "project_quota": "unknown"}


def limit_value(path):
    value = read(path)
    return "max" if value == "max" else int(value)


def cpu_limit(path):
    quota, period = read(path).split()
    return {"quota_us": "max" if quota == "max" else int(quota), "period_us": int(period)}


def cgroup():
    root = Path("/sys/fs/cgroup")
    if not (root / "cgroup.controllers").is_file():
        raise ProbeFailure("cgroup_v2_not_observed")
    relative = next((line[3:] for line in read("/proc/self/cgroup").splitlines()
                     if line.startswith("0::")), None)
    if relative is None or ".." in Path(relative).parts:
        raise ProbeFailure("cgroup_membership_unknown")
    current = (root / relative.lstrip("/")).resolve()
    if not current.is_relative_to(root):
        raise ProbeFailure("cgroup_outside_visible_root")
    chain = []
    while len(chain) < 32:
        chain.append({"level_from_probe": len(chain), "visible_root": current == root,
                      "cpu_max": observe(cpu_limit, current / "cpu.max"),
                      **{name: observe(limit_value, current / name) for name in
                         ("memory.max", "memory.current", "memory.swap.max", "memory.swap.current",
                          "pids.max", "pids.current")}})
        if current == root:
            break
        current = current.parent
    return {"version": 2, "controllers": sorted(set(read(root / "cgroup.controllers").split()) & CONTROLLERS),
            "cloudhelm_slice_exists": (root / "cloudhelm.slice").is_dir(),
            "probe_ancestor_limits": chain, "visible_root_reached": chain[-1]["visible_root"],
            "scope": "probe session and visible ancestors; not a project allocation"}


def network():
    counts, ports = Counter(), {str(port): Counter() for port in (22, 80, 443)}
    distinct = set()
    for line in command("ss", "-H", "-lntu").splitlines():
        fields = line.split()
        protocol, endpoint = fields[0], fields[4]
        if protocol not in {"tcp", "udp"}:
            raise ProbeFailure("listener_format_unknown")
        address, _, port_text = endpoint.rpartition(":")
        address = address.split("%", 1)[0].strip("[]")
        ip = None if address == "*" else ipaddress.ip_address(address)
        category = "wildcard" if ip is None or ip.is_unspecified else "loopback" if ip.is_loopback else "nonloopback"
        port = int(port_text)
        counts[protocol + "_" + category] += 1
        distinct.add((protocol, port))
        if str(port) in ports:
            ports[str(port)][protocol + "_" + category] += 1
    return {"listener_records": dict(counts), "distinct_protocol_ports": len(distinct),
            "allowlisted_ports": {port: dict(value) for port, value in ports.items()},
            "default_routes": {family: observe(lambda flag: len(json.loads(command("ip", "-j", flag, "route", "show", "default"))), flag)
                               for family, flag in (("ipv4", "-4"), ("ipv6", "-6"))},
            "dns_tls_firewall_reachability": "not_probed"}


def clock():
    values = dict(line.split("=", 1) for line in command(
        "timedatectl", "show", "--property=NTP", "--property=NTPSynchronized", "--property=Timezone").splitlines())
    return {"ntp_enabled": {"yes": True, "no": False}.get(values.get("NTP"), "unknown"),
            "ntp_synchronized": {"yes": True, "no": False}.get(values.get("NTPSynchronized"), "unknown"),
            "timezone": values.get("Timezone") if re.fullmatch(r"[A-Za-z_+-]+/[A-Za-z_+/-]+|UTC", values.get("Timezone", "")) else "unknown",
            "trusted_error_bound": "unknown"}


def docker():
    # Resolve local CLI metadata first, then explicitly pin a Unix socket.
    # This also prevents DOCKER_HOST/CONTEXT from redirecting the info query.
    endpoint = command("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    if not endpoint.startswith("unix:///"):
        return {"status": "nonlocal_endpoint_not_queried"}
    template = ("{{json .ServerVersion}}|{{json .NCPU}}|{{json .MemTotal}}|"
                "{{json .CgroupVersion}}|{{json .CgroupDriver}}|{{json .Driver}}|"
                "{{json .DockerRootDir}}|{{json .Containers}}|{{json .ContainersRunning}}|"
                "{{json .ContainersPaused}}|{{json .ContainersStopped}}|{{json .Images}}")
    keys = ("server_version", "logical_cpus", "memory_bytes", "cgroup_version", "cgroup_driver",
            "storage_driver", "root_dir", "containers", "running", "paused", "stopped", "images")
    fields = command("docker", "--host", endpoint, "info", "--format", template).split("|")
    if len(fields) != len(keys):
        raise ProbeFailure("docker_format_unknown")
    values = dict(zip(keys, map(json.loads, fields), strict=True))
    root_known = values.pop("root_dir") == "/var/lib/docker"
    numeric = ("logical_cpus", "memory_bytes", "containers", "running", "paused", "stopped", "images")
    if any(type(values[key]) is not int or values[key] < 0 for key in numeric):
        raise ProbeFailure("docker_numeric_format_unknown")
    if not re.fullmatch(r"\d+\.\d+\.\d+[a-zA-Z0-9.+~_-]{0,48}", str(values["server_version"])):
        raise ProbeFailure("docker_version_format_unknown")
    for key, allowed in {
        "cgroup_version": {"1", "2"}, "cgroup_driver": {"systemd", "cgroupfs", "none"},
        "storage_driver": {"overlay2", "overlayfs", "fuse-overlayfs", "aufs", "btrfs", "zfs", "vfs", "devicemapper"},
    }.items():
        values[key] = str(values[key]) if str(values[key]) in allowed else "unknown"
    return {**values, "endpoint_scheme": "unix", "root_is_allowlisted_var_lib_docker": root_known,
            "connection_scope": "local context with explicit host; Docker endpoint environment ignored",
            "endpoint_environment_override_present": any(name in os.environ for name in
                                                         ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG")),
            "container_configuration": "not_read", "per_owner_usage_and_disk_bytes": "unknown"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PATHS)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    started = datetime.now(UTC).isoformat()
    devices = {}
    result = {"collector_revision": REVISION, "profile": args.profile, "started_at": started,
              "system": observe(system), "memory": observe(memory), "load": observe(load),
              "storage": [observe(storage, path, devices) for path in PATHS[args.profile]],
              "cgroup": observe(cgroup), "network": observe(network), "clock": observe(clock),
              "tools": {name: observe(version, command_args) for name, command_args in VERSIONS.items()},
              "tool_presence_only": {name: shutil.which(name) is not None for name in
                                     ("quota", "xfs_quota", "systemd-run", "chronyc", "ssh")},
              "docker": observe(docker),
              "project_admission": {"approved_budget": "unknown", "unknown_occupancy_upper_bound": "unknown",
                                    "new_admission": "closed", "reason": "no verified project allocation or ledger",
                                    "scope": "diagnostic conclusion; not an implemented admission service"},
              "finished_at": datetime.now(UTC).isoformat()}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
