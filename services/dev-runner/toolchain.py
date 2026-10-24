"""Fixed public BuildKit toolchain and private Docker client for the P1 probe."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from modules.execution.docker_endpoint import socket_path

TOOLCHAIN_TAG = "moby/buildkit:v0.34.0-rootless"
TOOLCHAIN_DIGEST = "sha256:f9fad9251904053271e79f96b918e67f0750f34cd621f439b0c341b66ca31359"
PLATFORM = "linux/amd64"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/runner-probe")
DOCKER = "/usr/bin/docker"


class ProbeFailure(RuntimeError):
    """Only fixed categories are returned, never Docker configuration or secrets."""

    def __init__(self, category: str, diagnostic: str = "", detail: str = "") -> None:
        super().__init__(category)
        self.category = category
        self.diagnostic = diagnostic[:400]
        self.detail = detail[-600:]


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = path.lstat()
    if (not stat.S_ISDIR(state.st_mode) or state.st_uid != os.getuid()
            or state.st_mode & 0o077):
        raise ProbeFailure("probe_runtime_directory_not_private")


@dataclass(frozen=True)
class DockerClient:
    config_directory: Path
    endpoint: str = field(default_factory=socket_path)

    @classmethod
    def create(cls, directory: Path) -> DockerClient:
        private_directory(directory)
        config = directory / "docker-public"
        config.mkdir(mode=0o700)
        return cls(config)

    def run(self, *arguments: str, timeout: float = 20,
            required: bool = True) -> subprocess.CompletedProcess[str]:
        from .resource_context import current_group

        group = current_group()
        if arguments[0] == "create" and group is not None:
            parents = [value for value in arguments if value.startswith("--cgroup-parent=")]
            if parents and parents != ["--cgroup-parent=" + group.unit]:
                raise ProbeFailure("probe_resource_cgroup_parent_mismatch")
            if not parents:
                arguments = (arguments[0], "--cgroup-parent=" + group.unit, *arguments[1:])
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "DOCKER_CONFIG": str(self.config_directory)}
        try:
            result = subprocess.run(
                [DOCKER, "--host", "unix://" + self.endpoint, *arguments],
                env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ProbeFailure("probe_docker_command_timeout") from None
        except OSError:
            raise ProbeFailure("probe_docker_unavailable") from None
        if len(result.stdout) + len(result.stderr) > 2_000_000:
            raise ProbeFailure("probe_fixed_command_output_exceeded")
        if required and result.returncode:
            diagnostic = classify_diagnostic(result.stdout + result.stderr)
            raise ProbeFailure("probe_docker_" + arguments[0] + "_failed", diagnostic,
                               safe_diagnostic(result.stdout + result.stderr))
        return result


def classify_diagnostic(value: str) -> str:
    lowered = value.lower()
    for needle, category in (
        ("toomanyrequests", "public_registry_rate_limited"),
        ("no space left on device", "storage_limit_or_host_space_exhausted"),
        ("newuidmap", "rootless_uid_mapping_failed"),
        ("mount proc", "rootless_proc_mount_denied"),
        ("operation not permitted", "kernel_or_security_policy_denied"),
        ("read-only file system", "unexpected_writable_path_required"),
        ("no such file or directory", "toolchain_path_unavailable"),
        ("timeout", "operation_timed_out"),
        ("network is unreachable", "network_unavailable"),
    ):
        if needle in lowered:
            return category
    return "fixed_probe_command_rejected"


def safe_diagnostic(value: str) -> str:
    lines = [line for line in value.splitlines()
             if not re.search(r"password|credential|authorization|token|secret", line, re.IGNORECASE)]
    public = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"']+", "[endpoint]", " ".join(lines))
    return public[-600:]


def resolve_public_image(client: DockerClient) -> dict[str, str]:
    result = client.run("manifest", "inspect", TOOLCHAIN_TAG, timeout=90)
    index = json.loads(result.stdout)
    matches = [item for item in index.get("manifests", [])
               if item.get("platform", {}).get("os") == "linux"
               and item.get("platform", {}).get("architecture") == "amd64"]
    if len(matches) != 1:
        raise ProbeFailure("toolchain_linux_amd64_manifest_not_unique")
    digest = matches[0]["digest"]
    return {"tag": TOOLCHAIN_TAG, "platform": PLATFORM, "manifest_digest": digest}


def ensure_toolchain(client: DockerClient) -> dict[str, str]:
    if not TOOLCHAIN_DIGEST:
        raise ProbeFailure("toolchain_digest_not_fixed")
    reference = f"{TOOLCHAIN_TAG}@{TOOLCHAIN_DIGEST}"
    existing = client.run("image", "inspect", reference, "--format", "{{.Id}}", required=False)
    if existing.returncode:
        client.run("pull", "--platform", PLATFORM, reference, timeout=240)
    result = client.run("image", "inspect", reference, "--format",
                        "{{json .Id}} {{json .Os}} {{json .Architecture}} {{json .Config.User}}")
    values = result.stdout.strip().split()
    if (len(values) != 4 or [json.loads(item) for item in values[1:3]] != ["linux", "amd64"]
            or json.loads(values[3]) not in ("1000", "1000:1000")):
        raise ProbeFailure("toolchain_platform_or_user_mismatch")
    return {"reference": reference, "image_id": json.loads(values[0]),
            "platform": PLATFORM, "manifest_digest": TOOLCHAIN_DIGEST}


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    import tempfile

    private_directory(RUNTIME_ROOT)
    try:
        with tempfile.TemporaryDirectory(prefix="resolve-", dir=RUNTIME_ROOT) as temporary:
            print(json.dumps(resolve_public_image(DockerClient.create(Path(temporary))), ensure_ascii=False))
    except ProbeFailure as failure:
        print(json.dumps({"failure": failure.category, "diagnostic": failure.diagnostic,
                          "detail": failure.detail}))
        raise SystemExit(1) from None
