"""Deterministic source input inventory for the single P1.3-01 WSL method."""

import hashlib
from pathlib import Path

from packages.contracts.p1.resource_protocol import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
METHOD = "p1-3-01-shared-resources-r2"


def snapshot():
    paths = {ROOT / name for name in ("pyproject.toml", "uv.lock", ".python-version")}
    for directory in ("database", "modules", "services", "packages/contracts", "scripts/p1"):
        paths.update(path for path in (ROOT / directory).rglob("*.py") if "__pycache__" not in path.parts)
    paths.add(ROOT / "packages/contracts/p1/hub-openapi.json")
    files = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(paths)}
    return {"method_revision": METHOD, "source_tree_digest": canonical_digest(files),
            "file_count": len(files), "files": files}
