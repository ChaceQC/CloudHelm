"""Real observations of the fixed rootless builder; accepts no project commands."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from packages.contracts.p1.runner_contracts import CapabilityEvidence

from . import policy
from .toolchain import DockerClient, ProbeFailure, classify_diagnostic, safe_diagnostic

PROBE_SCRIPT = """set -eu
b=/bin/busybox
{
  printf 'uid=%s\\n' "$($b id -u)"
  printf 'uid_map=%s\\n' "$($b cat /proc/self/uid_map | $b tr '\\n' '|')"
  printf 'pid_ns=%s\\n' "$($b readlink /proc/self/ns/pid)"
  printf 'net_ns=%s\\n' "$($b readlink /proc/self/ns/net)"
  printf 'proc_one=%s\\n' "$($b cat /proc/1/comm)"
  printf 'storage_kib=%s\\n' "$($b df -k /probe-fill | $b awk 'NR == 2 {print $2}')"
} > /probe-result
for path in /var/run/docker.sock /run/docker.sock /probe/input /root/.docker /app/.git; do
  test ! -e "$path" || exit 21
done
printf 'control_paths=absent\\n' >> /probe-result
set +e
message=$($b dd if=/dev/zero of=/probe-fill/bytes bs=65536 count=32 2>&1)
write_result=$?
set -e
$b rm -f /probe-fill/bytes
test "$write_result" -ne 0 || exit 22
case "$message" in *"No space left on device"*) ;; *) exit 23;; esac
printf 'tmpfs_exhaustion=enospc\\n' >> /probe-result
if $b nc -w 1 127.0.0.1 @PORT@ </dev/null >/dev/null 2>&1; then exit 24; fi
if $b nc -w 1 1.1.1.1 443 </dev/null >/dev/null 2>&1; then exit 25; fi
routes=$($b cat /proc/net/route | $b wc -l)
test "$routes" -eq 1 || exit 26
printf 'network=host_loopback_and_public_unreachable\\n' >> /probe-result
$b sleep 300 &
printf 'background_pid=%s\\n' "$!" >> /probe-result
$b sleep 3
"""
DOCKERFILE = """FROM scratch
COPY rootfs/ /
RUN --network=none --mount=type=tmpfs,target=/probe-fill,size=1048576 ["/bin/busybox", "sh", "/probe.sh"]
"""


def evidence(name: str, passed: bool, reason: str, *observations: str) -> CapabilityEvidence:
    return CapabilityEvidence(capability=name, status="verified" if passed else "unsupported",
                              reason=reason, observations=observations)


def process_identity(pid: int) -> str | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return value.rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


class CapabilityProbe:
    def __init__(self, client: DockerClient, operation_id: str, directory: Path,
                 image: str, started: float) -> None:
        self.client, self.operation_id, self.directory = client, operation_id, directory
        self.image, self.started = image, started
        self.container_id: str | None = None
        self.cgroup: Path | None = None
        self.records: dict[str, CapabilityEvidence] = {}
        self.processes: dict[int, str | None] = {}
        self.sleeper_processes: dict[int, str | None] = {}
        self.outer_pid_namespace = ""
        self.host_network_namespace = os.readlink("/proc/self/ns/net")
        self.probe_input_digest: str | None = None
        self.observed_storage: dict[str, int] = {}

    def remaining(self, ceiling: int = 20) -> float:
        remaining = policy.WALL_SECONDS - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ProbeFailure("probe_execution_deadline_exceeded")
        return min(ceiling, remaining)

    def metadata(self) -> dict:
        result = self.client.run("inspect", self.container_id, timeout=10)
        metadata = json.loads(result.stdout)[0]
        policy.ensure_owned(metadata, self.operation_id)
        return metadata

    def execute(self, *arguments: str, ceiling: int = 20, required: bool = True):
        return self.client.run("exec", "--user=1000:1000", self.container_id, *arguments,
                               timeout=self.remaining(ceiling), required=required)

    def create(self) -> None:
        existing = self.client.run("ps", "--all", "--quiet", "--filter", f"label={policy.SCOPE_LABEL}")
        if existing.stdout.strip():
            raise ProbeFailure("probe_previous_execution_requires_reconciliation")
        context = self.directory / "context"
        context.mkdir(mode=0o700)
        result = self.client.run(*policy.container_arguments(self.operation_id, self.image, context))
        self.container_id = result.stdout.strip()
        if len(self.container_id) != 64:
            raise ProbeFailure("probe_container_identity_unavailable")
        self.client.run("start", self.container_id, timeout=self.remaining())
        self._wait_for_worker()

    def _wait_for_worker(self) -> None:
        for _ in range(25):
            result = self.execute("buildctl", "--addr", "unix:///run/user/1000/buildkit/buildkitd.sock",
                                  "debug", "workers", "--verbose", required=False)
            if result.returncode == 0:
                labels = {}
                for line in result.stdout.splitlines():
                    key, separator, value = line.partition(":")
                    if separator:
                        labels[key.strip()] = value.strip()
                native = labels.get("org.mobyproject.buildkit.worker.snapshotter") == "native"
                sandbox = labels.get("org.mobyproject.buildkit.worker.oci.process-mode") == "sandbox"
                if not native or not sandbox:
                    raise ProbeFailure("probe_worker_snapshotter_or_process_sandbox_mismatch")
                return
            if not self.metadata()["State"]["Running"]:
                logs = self.client.run("logs", "--tail=30", self.container_id, required=False)
                raise ProbeFailure("probe_rootless_worker_start_failed",
                                   classify_diagnostic(logs.stdout + logs.stderr),
                                   safe_diagnostic(logs.stdout + logs.stderr))
            time.sleep(0.2)
        raise ProbeFailure("probe_worker_readiness_unconfirmed")

    def observe_boundary(self) -> None:
        metadata = self.metadata()
        host = metadata["HostConfig"]
        mounts = metadata["Mounts"]
        expected_context = str(self.directory / "context")
        binds = [item for item in mounts if item["Type"] == "bind"]
        allowed_mounts = {"/probe/input", "/home/user/.local/share/buildkit", "/run/user/1000", "/tmp"}
        boundary = (metadata["Config"]["User"] == "1000:1000" and host["ReadonlyRootfs"]
                    and not host["Privileged"] and not host.get("Devices")
                    and host["NetworkMode"] == "none" and host["IpcMode"] == "private"
                    and not host.get("CapAdd")
                    and len(binds) == 1 and binds[0]["Source"] == expected_context
                    and binds[0]["Destination"] == "/probe/input" and not binds[0]["RW"]
                    and all(item["Destination"] in allowed_mounts and item["Type"] in ("bind", "tmpfs")
                            for item in mounts)
                    and set(host["Tmpfs"]) == allowed_mounts - {"/probe/input"})
        self.records["filesystem_boundary"] = evidence("filesystem_boundary", boundary,
            "actual_container_mounts_and_security", "readonly_root=true", "only_fixed_context_bind=true",
            "privileged=false", "devices=none", "host_socket=absent", "additional_capabilities=none")
        if not boundary:
            raise ProbeFailure("probe_container_boundary_mismatch")
        pid = metadata["State"]["Pid"]
        groups = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").strip().splitlines()
        unified = next((line[3:] for line in groups if line.startswith("0::/")), None)
        if unified is None:
            raise ProbeFailure("probe_unified_parent_cgroup_unavailable")
        self.cgroup = Path("/sys/fs/cgroup") / unified.lstrip("/")
        if not self.cgroup.resolve().is_relative_to(Path("/sys/fs/cgroup")):
            raise ProbeFailure("probe_parent_cgroup_path_invalid")
        for name, filename, expected in (
            ("group_cpu", "cpu.max", f"{policy.CPU_QUOTA} {policy.CPU_PERIOD}"),
            ("group_memory", "memory.max", str(policy.MEMORY_BYTES)),
            ("group_pids", "pids.max", str(policy.PIDS_LIMIT)),
        ):
            observed = (self.cgroup / filename).read_text(encoding="utf-8").strip()
            swap = (self.cgroup / "memory.swap.max").read_text(encoding="utf-8").strip()
            passed = observed == expected and (name != "group_memory" or swap == "0")
            self.records[name] = evidence(name, passed, "kernel_parent_cgroup_limit",
                                          f"{filename}={observed}", f"memory.swap.max={swap}")
            if not passed:
                raise ProbeFailure("probe_parent_cgroup_limit_mismatch")
        self.outer_pid_namespace = self.execute("readlink", "/proc/self/ns/pid").stdout.strip()
        for path, expected in (("/home/user/.local/share/buildkit", policy.STATE_BYTES),
                               ("/run/user/1000", policy.TMP_BYTES), ("/tmp", policy.TMP_BYTES),
                               ("/dev/shm", policy.SHM_BYTES)):
            sizes = self.execute("stat", "-f", "-c", "%S %b", path).stdout.split()
            self.observed_storage[path] = int(sizes[0]) * int(sizes[1])
            if self.observed_storage[path] != expected:
                raise ProbeFailure("probe_builder_tmpfs_limit_mismatch")
        self._observe_processes()

    def _observe_processes(self) -> None:
        result = self.client.run("top", self.container_id, "-eo", "pid,comm", timeout=self.remaining())
        for line in result.stdout.splitlines()[1:]:
            fields = line.split()
            if len(fields) != 2 or not fields[0].isdigit():
                raise ProbeFailure("probe_process_observation_invalid")
            pid, command = int(fields[0]), fields[1]
            identity = process_identity(pid)
            if identity is None:
                continue
            try:
                group = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").strip()
                command_line = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            except FileNotFoundError:
                continue
            expected = "/" + str(self.cgroup.relative_to("/sys/fs/cgroup"))
            if not any(line == f"0::{expected}" or line.startswith(f"0::{expected}/")
                       for line in group.splitlines()):
                raise ProbeFailure("probe_child_outside_parent_cgroup")
            self.processes[pid] = identity
            if b"sleep" in command_line and b"300" in command_line:
                self.sleeper_processes[pid] = identity

    def prepare_input(self, host_port: int) -> None:
        context = self.directory / "context"
        rootfs = context / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        (rootfs / "lib").mkdir()
        for source, destination in (("/bin/busybox", rootfs / "bin/busybox"),
                                     ("/lib/ld-musl-x86_64.so.1", rootfs / "lib/ld-musl-x86_64.so.1")):
            self.client.run("cp", f"{self.container_id}:{source}", str(destination))
        (rootfs / "probe.sh").write_text(PROBE_SCRIPT.replace("@PORT@", str(host_port)), encoding="utf-8")
        (context / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        manifest = {str(path.relative_to(context)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(context.rglob("*")) if path.is_file()}
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.probe_input_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()

    def run_fixed_build(self) -> None:
        with socket.socket() as sentinel:
            sentinel.bind(("127.0.0.1", 0))
            sentinel.listen(2)
            port = sentinel.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass
            self.prepare_input(port)
            with ThreadPoolExecutor(max_workers=1) as executor:
                build = executor.submit(self.execute, "buildctl", "--addr",
                    "unix:///run/user/1000/buildkit/buildkitd.sock", "build",
                    "--frontend=dockerfile.v0", "--local=context=/probe/input",
                    "--local=dockerfile=/probe/input", "--opt=platform=linux/amd64", "--no-cache",
                    "--progress=plain", "--output=type=local,dest=/tmp/probe-output", ceiling=45)
                while not build.done():
                    self._observe_processes()
                    time.sleep(0.15)
                build.result()
        output = self.execute("cat", "/tmp/probe-output/probe-result").stdout
        facts = dict(line.split("=", 1) for line in output.strip().splitlines())
        self._evaluate_build(facts)

    def _evaluate_build(self, facts: dict[str, str]) -> None:
        mappings = [row.split() for row in facts["uid_map"].split("|") if row.strip()]
        mapped_uid = facts["uid"] == "0" and ["0", "1000", "1"] in mappings
        self.records["rootless_uid"] = evidence("rootless_uid", mapped_uid,
            "actual_exec_user_namespace_mapping", f"run_uid={facts['uid']}", f"uid_map={facts['uid_map']}")
        pid_isolated = facts["pid_ns"] != self.outer_pid_namespace and facts["proc_one"] not in (
            "buildkitd", "rootlesskit")
        self.records["pid_proc_isolation"] = evidence("pid_proc_isolation", pid_isolated,
            "actual_exec_pid_namespace_and_proc", f"run={facts['pid_ns']}",
            f"outer={self.outer_pid_namespace}", f"proc_one={facts['proc_one']}")
        remaining = [pid for pid, identity in self.sleeper_processes.items()
                     if process_identity(pid) == identity]
        sandbox = bool(self.sleeper_processes) and not remaining
        self.records["process_sandbox"] = evidence("process_sandbox", sandbox,
            "worker_sandbox_and_background_process_cleanup", "background_duration_seconds=300",
            f"observed_sleepers={len(self.sleeper_processes)}",
            f"remaining_sleepers={len(remaining)}", f"group_processes_observed={len(self.processes)}")
        self.records["tmpfs_limit"] = evidence("tmpfs_limit",
            facts["tmpfs_exhaustion"] == "enospc" and facts["storage_kib"] == "1024",
            "actual_bounded_tmpfs_write_rejected", "exec_tmpfs_kib=1024", "excess_write=ENOSPC",
            *(f"tmpfs_bytes[{path}]={size}" for path, size in self.observed_storage.items()),
            "persistent_disk_quota=unverified")
        self.records["network_isolation"] = evidence("network_isolation",
            facts["net_ns"] != self.host_network_namespace
            and facts["network"] == "host_loopback_and_public_unreachable",
            "actual_host_sentinel_public_egress_and_namespace", f"run={facts['net_ns']}",
            f"host={self.host_network_namespace}", "ipv4_routes=none", "docker_network=none")

    def stop_and_remove(self) -> CapabilityEvidence:
        if self.container_id is None:
            return CapabilityEvidence(capability="stop_confirmation", status="unverified", reason="not_started")
        metadata = self.metadata()
        if metadata["State"]["Running"]:
            self.client.run("stop", "--time=3", self.container_id, timeout=15)
        stopped = self.metadata()
        remaining = [pid for pid, identity in self.processes.items() if process_identity(pid) == identity]
        populated = False
        if self.cgroup is not None and self.cgroup.exists():
            populated = "populated 1" in (self.cgroup / "cgroup.events").read_text(encoding="utf-8")
        verified = not stopped["State"]["Running"] and stopped["State"]["Pid"] == 0 and not remaining and not populated
        if not verified:
            raise ProbeFailure("probe_stop_unconfirmed_reconciliation_required")
        self.client.run("rm", "--volumes", self.container_id, timeout=15)
        exists = self.client.run("ps", "--all", "--quiet", "--filter",
                                f"label=cloudhelm.operation_id={self.operation_id}")
        if exists.stdout.strip():
            raise ProbeFailure("probe_owned_container_cleanup_unconfirmed")
        if self.cgroup is None:
            return CapabilityEvidence(capability="stop_confirmation", status="unverified",
                reason="host_process_group_not_observed", observations=(
                    "docker_running=false", "docker_pid=0", "owned_container_removed=true"))
        return evidence("stop_confirmation", True, "docker_and_host_process_stop_confirmed",
                        f"tracked_processes={len(self.processes)}", "remaining_processes=0",
                        "cgroup_populated=false", "owned_container_removed=true")
