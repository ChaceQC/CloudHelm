"""One bounded rootless BuildKit run using a fixed read-only local OCI base."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .buildkit_container import OfflineBuildKitContainer, SOCKET
from .toolchain import ProbeFailure

METHOD = "p1-offline-image-probe-r1"
SCOPE = "p1-offline-image-probe"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/offline-image-probe")
CPU_QUOTA, CPU_PERIOD = 200000, 100000
MEMORY_BYTES, PIDS_LIMIT = 2 * 1024**3, 256
STATE_BYTES, OUTPUT_BYTES = 768 * 1024**2, 256 * 1024**2
TEMP_BYTES, SHM_BYTES = 16 * 1024**2, 1024**2
WALL_SECONDS = 180
VERSION_SENTINEL = "CLOUDHELM_OFFLINE_PYTHON=3.12.13"
DOCKERFILE = '''FROM pythonbase
RUN --network=none ["python", "-I", "-c", "import sys; assert sys.version_info[:3] == (3, 12, 13); print('CLOUDHELM_OFFLINE_PYTHON=3.12.13', flush=True)"]
'''


class OfflineImageRuntime(OfflineBuildKitContainer):
    """Historical offline image check with the shared BuildKit container boundary."""

    def remaining(self, ceiling: int = 20) -> float:
        remaining = WALL_SECONDS - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ProbeFailure("offline_execution_deadline_exceeded")
        return min(ceiling, remaining)

    def metadata(self) -> dict:
        metadata = json.loads(self.client.run("inspect", self.container_id, timeout=10).stdout)[0]
        labels = metadata["Config"].get("Labels") or {}
        if (labels.get("cloudhelm.scope") != SCOPE
                or labels.get("cloudhelm.operation_id") != self.operation_id
                or labels.get("cloudhelm.method") != METHOD):
            raise ProbeFailure("offline_container_ownership_mismatch")
        return metadata

    def _binds(self) -> dict[str, str]:
        return {"/probe/context": str(self.directory / "context"),
                "/probe/base": str(self.directory / "base-layout")}

    @staticmethod
    def _tmpfs() -> dict[str, tuple[int, str]]:
        return {"/home/user/.local/share/buildkit": (STATE_BYTES, "0700"),
                "/run/user/1000": (TEMP_BYTES, "0700"), "/tmp": (TEMP_BYTES, "1777"),
                "/probe/output": (OUTPUT_BYTES, "0700")}

    def create(self) -> None:
        for scope in (SCOPE, "p1-runner-probe"):
            existing = self.client.run("ps", "--all", "--quiet", "--filter", f"label=cloudhelm.scope={scope}")
            if existing.stdout.strip():
                raise ProbeFailure("offline_previous_execution_requires_reconciliation")
        context = self.directory / "context"
        context.mkdir(mode=0o700)
        descriptor = os.open(context / "Dockerfile", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(DOCKERFILE)
        self._create_builder(scope=SCOPE, method=METHOD, binds=self._binds(), tmpfs=self._tmpfs(),
            cpu_quota=CPU_QUOTA, cpu_period=CPU_PERIOD, memory=MEMORY_BYTES, pids=PIDS_LIMIT,
            shm=SHM_BYTES, error_prefix="offline")

    def observe_boundary(self) -> dict:
        observed, storage = self._observe_builder(tmpfs=self._tmpfs(), cpu_quota=CPU_QUOTA,
            cpu_period=CPU_PERIOD, memory=MEMORY_BYTES, pids=PIDS_LIMIT, shm=SHM_BYTES,
            error_prefix="offline")
        return {"kernel_limits": observed, "tmpfs_bytes": storage,
                "tmpfs_capacity_sum": sum(storage.values()), "network": "none", "readonly_root": True,
                "process_sandbox": True, "snapshotter": "native", "source_binds_readonly": True,
                "execution_wall_seconds": WALL_SECONDS,
                "security_exceptions": ["seccomp=unconfined", "systempaths=unconfined"]}

    def export_image(self, manifest_digest: str) -> dict:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            build = executor.submit(self.execute, "buildctl", "--addr", SOCKET, "build",
                "--frontend=dockerfile.v0", "--local=context=/probe/context", "--local=dockerfile=/probe/context",
                "--oci-layout=python=/probe/base", "--opt=context:pythonbase=oci-layout://python@" + manifest_digest,
                "--opt=platform=linux/amd64", "--no-cache", "--progress=plain",
                "--output=type=oci,dest=/probe/output/image.oci.tar,oci-mediatypes=true,compression=gzip",
                "--metadata-file=/probe/output/build-metadata.json", ceiling=120)
            while not build.done():
                self._observe_processes()
                time.sleep(0.15)
            result = build.result()
        if VERSION_SENTINEL not in result.stdout + result.stderr:
            raise ProbeFailure("offline_python_version_command_not_observed")
        metadata = json.loads(self.execute("cat", "/probe/output/build-metadata.json").stdout)
        digest = self.execute("sha256sum", "/probe/output/image.oci.tar").stdout.split()[0]
        size = int(self.execute("stat", "-c", "%s", "/probe/output/image.oci.tar").stdout)
        if not 0 < size <= OUTPUT_BYTES:
            raise ProbeFailure("offline_output_archive_size_invalid")
        target = self.directory / "image.oci.tar"
        self._collect_archive(target)
        if target.stat().st_size != size:
            raise ProbeFailure("offline_collected_archive_size_mismatch")
        self._observe_processes()
        return {"archive_path": str(target), "archive_digest": "sha256:" + digest, "archive_bytes": size,
                "exporter_manifest_digest": metadata.get("containerimage.digest"),
                "exporter_config_digest": metadata.get("containerimage.config.digest"),
                "python_version": "3.12.13", "cache_policy": "no-cache"}

    def stopped_resources(self) -> dict:
        stopped = self.stop_and_remove()
        return {"confirmation": stopped.model_dump(mode="json"),
                "process_resources_released": stopped.status == "verified",
                "memory_peak_bytes": getattr(self, "memory_peak", None),
                "host_archive_bytes_are_retained": True}
