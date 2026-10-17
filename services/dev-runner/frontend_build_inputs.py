"""Only the fixed notes frontend enters this explicit offline recipe variant."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from modules.artifacts.content_files import file_shape
from packages.contracts.p1.npm_cache import INSTALL_OPTIONS, LOCK_DIGEST, PACKAGE_DIGEST

from .toolchain import ProbeFailure

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "examples/standalone-project/frontend"
RECIPE = ROOT / "infra/p1/reference-build/frontend.offline.Dockerfile"
SOURCE_DIGESTS = {
    "package.json": PACKAGE_DIGEST[7:], "package-lock.json": LOCK_DIGEST[7:],
    "index.html": "c271448b2dabaaf6629267df4ee9bc3ae09f152eba1a66cbbce38562e02b7fd6",
    "tsconfig.json": "298c25324471c522cdf5463f26e2783c5ede55105bf81da617cb118d3defba16",
    "vite.config.ts": "2cff497995117c948c679934559687393fd8c7df9fae5b9807a0325a195d3bdb",
    "nginx.conf": "c10536d9fbf7a62c84b730aa9133ea1a35b6b05c5e595b3c9e0ef46616b6ee44",
    "src/api.ts": "d6a8755643957615dd888f617f6587394909633f3adcca38b7ef89e91808d779",
    "src/App.tsx": "a09b7c6a490e320db40b7bbad060344d6a933e40e18c3f871ddc6c405a95f60b",
    "src/main.tsx": "ccbefe7be6c69706a1bb01c4c3f20492eb002435af6ba7e5a6d45f7c6aa3a140",
    "src/styles.css": "5f6d7e79cf6550f595d6179b0990193cc026050e58fe0189bf54deff71d21b2e",
}


def verify_source(inputs: dict[str, bytes], expected_manifest_digest: str | None = None) -> dict:
    if (set(inputs) != set(SOURCE_DIGESTS) or any(not isinstance(raw, bytes)
            or len(raw) > 128 * 1024 for raw in inputs.values())):
        raise ProbeFailure("frontend_source_members_or_bounds_mismatch")
    actual = {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}
    if actual != SOURCE_DIGESTS:
        raise ProbeFailure("frontend_fixed_source_digest_mismatch")
    files = {name: {"sha256": "sha256:" + actual[name], "bytes": len(inputs[name])}
             for name in sorted(inputs)}
    raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if expected_manifest_digest is not None and digest != expected_manifest_digest:
        raise ProbeFailure("frontend_source_manifest_digest_mismatch")
    return {"files": files, "manifest_digest": digest,
            "file_count": len(files), "bytes": sum(map(len, inputs.values()))}


def _read_fixed(path: Path) -> bytes:
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ProbeFailure("frontend_source_path_invalid")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 128 * 1024:
                raise ProbeFailure("frontend_source_file_unsupported")
            data = stream.read(128 * 1024 + 1)
            if file_shape(os.fstat(stream.fileno())) != file_shape(before) or len(data) != before.st_size:
                raise ProbeFailure("frontend_source_changed_during_read")
            return data
    finally:
        os.close(directory)


def reference_inputs(frontend: Path = FRONTEND) -> dict[str, bytes]:
    """Read the supported frontend subtree, including an independent candidate view."""
    inputs = {name: _read_fixed(frontend / name) for name in SOURCE_DIGESTS}
    verify_source(inputs)
    return inputs


def prepare_context(directory: Path, source_inputs: dict[str, bytes], *,
                    expected_manifest_digest: str) -> dict:
    inputs = dict(source_inputs)
    source = verify_source(inputs, expected_manifest_digest)
    recipe = _read_fixed(RECIPE)
    command = b"npm ci " + " ".join(INSTALL_OPTIONS).encode("ascii")
    if recipe.count(command) != 1:
        raise ProbeFailure("frontend_recipe_seed_install_options_mismatch")
    context = directory / "context"
    context.mkdir(mode=0o700)
    (context / "src").mkdir(mode=0o700)
    for name, raw in (inputs | {"Dockerfile": recipe}).items():
        descriptor = os.open(context / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    (context / "src").chmod(0o500)
    context.chmod(0o500)
    return source | {"recipe_digest": "sha256:" + hashlib.sha256(recipe).hexdigest(),
        "recipe_variant": "fixed-notes-npm-offline-ignore-scripts-r2",
        "install_options": INSTALL_OPTIONS}
