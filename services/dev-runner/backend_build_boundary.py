"""One fixed backend builder envelope, checked against Linux kernel facts."""

from __future__ import annotations

from pathlib import Path

from .buildkit_container import (
    CPU_PERIOD, CPU_QUOTA, INSTALL_CACHE_BYTES, INSTALL_TEMP_BYTES, MEMORY_BYTES, OUTPUT_BYTES,
    PIDS_LIMIT, ProductBuildBoundary, SHM_BYTES, SOCKET, STATE_BYTES, TEMP_BYTES,
)

METHOD = "p1-backend-offline-build-r1"
SCOPE = "p1-backend-offline-build"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/backend-build-check")
WALL_SECONDS = 420


class BackendBuildBoundary(ProductBuildBoundary):
    scope, method, error_prefix, wall_seconds = SCOPE, METHOD, "backend", WALL_SECONDS

    def _sources(self) -> dict[str, Path]:
        return {"/probe/context": self.directory / "context",
                "/probe/base": self.directory / "base-layout", "/probe/python-seed": self.seed}
