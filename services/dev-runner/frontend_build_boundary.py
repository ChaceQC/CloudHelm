"""Fixed frontend builder envelope, observed at the real Linux boundary."""

from __future__ import annotations

from pathlib import Path

from .buildkit_container import (
    CPU_PERIOD, CPU_QUOTA, INSTALL_CACHE_BYTES, INSTALL_TEMP_BYTES, MEMORY_BYTES, OUTPUT_BYTES,
    PIDS_LIMIT, ProductBuildBoundary, SHM_BYTES, SOCKET, STATE_BYTES, TEMP_BYTES,
)

METHOD = "p1-frontend-offline-build-r2"
SCOPE = "p1-frontend-offline-build"
RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/frontend-build-check")
WALL_SECONDS = 360


class FrontendBuildBoundary(ProductBuildBoundary):
    scope, method, error_prefix, wall_seconds = SCOPE, METHOD, "frontend", WALL_SECONDS

    def _sources(self) -> dict[str, Path]:
        return {"/probe/context": self.directory / "context", "/probe/npm-seed": self.seed,
                "/probe/node": self.directory / "node-layout", "/probe/nginx": self.directory / "nginx-layout"}
