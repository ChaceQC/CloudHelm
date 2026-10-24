"""Fixed in-container HTTP and reload-process probes for the notes profile."""

from __future__ import annotations

from pathlib import Path

from modules.workspaces.candidate_writers import process_start_ticks

from .toolchain import DockerClient, ProbeFailure
from .workspace_development_recipe import HTTP_PROBE, parse_backend_probe


def probe_workspace_backend(client: DockerClient, container_id: str) -> dict:
    result = client.run("exec", container_id, "/environment/bin/python", "-B", "-I", "-c", HTTP_PROBE,
        timeout=8, required=False)
    if result.returncode:
        raise ProbeFailure("workspace_development_http_probe_not_ready")
    return parse_backend_probe(result.stdout)


def workspace_server_process_id(client: DockerClient, container_id: str, cgroup_path: Path) -> str:
    result = client.run("top", container_id, "-eo", "pid,args", timeout=10)
    candidates = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        if "multiprocessing.spawn" in fields[1] or "spawn_main" in fields[1]:
            candidates.append(int(fields[0]))
    if len(candidates) != 1:
        raise ProbeFailure("workspace_development_server_process_identity_unconfirmed")
    pid = candidates[0]
    try:
        cgroups = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        selected = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                         for line in cgroups if line.startswith("0::/")), None)
        if selected is None or not selected.is_relative_to(cgroup_path):
            raise ProbeFailure("workspace_development_server_process_outside_parent")
        ticks = process_start_ticks(pid)
    except ProbeFailure:
        raise
    except (OSError, ValueError, IndexError):
        raise ProbeFailure("workspace_development_server_process_identity_unconfirmed") from None
    return f"{container_id[:16]}:{pid}:{ticks}"
