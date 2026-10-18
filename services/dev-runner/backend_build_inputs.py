"""The fixed backend recipe consumes verified bytes from a trusted source snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from .python_dependencies import INPUT_DIGESTS, derived_project
from .toolchain import ProbeFailure, TOOLCHAIN_DIGEST, private_directory

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "examples/standalone-project/backend"
RECIPE = ROOT / "infra/p1/reference-build/backend.offline.Dockerfile"
MAX_SOURCE_FILE_BYTES = 128 * 1024
SOURCE_DIGESTS = INPUT_DIGESTS | {
    ".dockerignore": "sha256:08bc12907214f2b0272a6e82f035e3cbbaf7ac16defb4ab4a95302545308d317",
    "Dockerfile": "sha256:b28e48358b722b5bf6bc3e05040e250c44c49c6e9d1d86bde2b6add1fb17cbdf",
    "README.md": "sha256:22fd4c90f4234043320804eb18480b9e6ddef28acaeda82a66ca939e232e5688",
    "openapi.json": "sha256:05d0a9a87378219d08f3f5a696199271fac9191eb5daf2b52a1a7626302d91e2",
    "alembic.ini": "sha256:6c18a6befe7a7b2d6866587cd2080a3bff803f82a80d1bdaa66bffe759405036",
    "app/__init__.py": "sha256:ad9e6e2a816f005ad862273c5941cb2fd261ca83bf7a406d54d27dcac7794e60",
    "app/database.py": "sha256:51d5a1d46dc61dcc8af8fe6c0c06d7bb5232b231fdb0945393af32858840549c",
    "app/main.py": "sha256:437085b28750bc19b50908cd8d51bd32584438388c89c57ecbe39db9cfabded3",
    "app/models.py": "sha256:de5d75aee0093e812fb5eb081ec6637407a2d1f4a193df0973a4f67b923fbfec",
    "app/readiness.py": "sha256:37174dd7105c56aa1638503ea00f55e14ed5c54dd24c08b8924e3f1b0a3e2de4",
    "app/routes.py": "sha256:79416f4e1932568abc1819d32176ea8abd4f360a648d3243795f9722d1fca197",
    "app/schemas.py": "sha256:51b4cf3230790f2e18fa6058bc4cff143d6f679e7c1fa63b987937d271e55fa7",
    "migrations/env.py": "sha256:b051c59170abf1450caf51aa170b533b590d317d9f447263c08705ec1d1a58d8",
    "migrations/versions/0001_create_notes.py": "sha256:7698b5b5f6554bd89026d808bab8a0acfa07ba02b25a9e28cf65483bf6ef0c6f",
    "migrations/versions/0002_add_updated_at_index.py": "sha256:5b2961617293966d5b39427ab3a57ddc6bc96ed0ee31d94d997ba07779399f5f",
}
RUNTIME_SOURCE = tuple(name for name in SOURCE_DIGESTS if name.startswith(("app/", "migrations/"))) + (
    "alembic.ini", "pyproject.toml", "uv.lock", ".python-version")


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _source_receipt(source_files: Mapping[str, bytes]) -> dict:
    actual = {name: digest(raw) for name, raw in source_files.items()}
    files = {name: {"sha256": actual[name], "bytes": len(source_files[name])}
             for name in sorted(source_files)}
    manifest = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"files": files, "manifest_digest": digest(manifest), "file_count": len(files),
            "bytes": sum(map(len, source_files.values()))}


def verify_source(source_files: Mapping[str, bytes]) -> dict:
    if (not isinstance(source_files, Mapping) or set(source_files) != set(SOURCE_DIGESTS)
            or any(type(raw) is not bytes or len(raw) > MAX_SOURCE_FILE_BYTES for raw in source_files.values())):
        raise ProbeFailure("backend_source_members_or_bounds_mismatch")
    actual = {name: digest(raw) for name, raw in source_files.items()}
    if actual != SOURCE_DIGESTS:
        raise ProbeFailure("backend_fixed_source_digest_mismatch")
    return _source_receipt(source_files)


def _read_fixed(path: Path) -> bytes:
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
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_size > MAX_SOURCE_FILE_BYTES):
                raise ProbeFailure("backend_source_file_unsupported")
            raw = stream.read(MAX_SOURCE_FILE_BYTES + 1)
            if os.fstat(stream.fileno()) != before or len(raw) != before.st_size:
                raise ProbeFailure("backend_source_changed_during_read")
            return raw
    finally:
        os.close(directory)


def reference_inputs(source_root: Path = BACKEND) -> dict[str, bytes]:
    """Development-method adapter; production callers supply fixed candidate bytes."""
    source_files = {name: _read_fixed(source_root / name) for name in SOURCE_DIGESTS}
    verify_source(source_files)
    return source_files


def _write_context(directory: Path, source: Mapping[str, bytes], receipt: dict, *, source_ref: str,
                   distributions: Mapping[str, str], context_name: str | None = None,
                   seal_bundle: bool = True) -> dict:
    if not isinstance(source_ref, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}", source_ref):
        raise ProbeFailure("backend_source_reference_invalid")
    if context_name is not None and not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", context_name):
        raise ProbeFailure("backend_source_context_name_invalid")
    private_directory(directory)
    recipe = _read_fixed(RECIPE)
    bundle = directory / "context"
    if context_name is None:
        context = bundle
        context.mkdir(mode=0o700)
    else:
        if bundle.exists() or bundle.is_symlink():
            state = bundle.lstat()
            if not stat.S_ISDIR(state.st_mode) or state.st_uid != os.getuid():
                raise ProbeFailure("backend_source_context_bundle_invalid")
        else:
            bundle.mkdir(mode=0o700)
        context = bundle / context_name
        context.mkdir(mode=0o700)
    files = source | {"Dockerfile": recipe, "derived-pyproject.toml": derived_project(source),
        "expected-distributions.json": json.dumps(dict(distributions), sort_keys=True).encode("utf-8")}
    for name, raw in files.items():
        target = context / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    for child in sorted(context.rglob("*"), reverse=True):
        if child.is_dir():
            child.chmod(0o500)
    context.chmod(0o500)
    if context_name is None or seal_bundle:
        bundle.chmod(0o500)
    return receipt | {"source_ref": source_ref, "recipe_digest": digest(recipe),
        "recipe_variant": "fixed-notes-python-offline-r2", "derived_project_digest": digest(derived_project(source))}


def prepare_context(directory: Path, source_files: Mapping[str, bytes], *, source_ref: str,
                    distributions: Mapping[str, str], context_name: str | None = None,
                    seal_bundle: bool = True) -> dict:
    """Prepare a strictly fixed candidate; optional names isolate method contexts."""
    source = dict(source_files)
    receipt = verify_source(source)
    return _write_context(directory, source, receipt, source_ref=source_ref,
                          distributions=distributions, context_name=context_name,
                          seal_bundle=seal_bundle)


def seal_context_bundle(directory: Path) -> None:
    """Seal all method contexts before the trusted builder pins its read-only bind."""
    bundle = directory / "context"
    if bundle.is_symlink() or not bundle.is_dir():
        raise ProbeFailure("backend_source_context_bundle_invalid")
    entries = [bundle, *bundle.rglob("*")]
    for entry in entries:
        state = entry.lstat()
        if (state.st_uid != os.getuid() or not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode))
                or (entry != bundle and state.st_mode & 0o222)):
            raise ProbeFailure("backend_source_context_member_invalid")
    bundle.chmod(0o500)


def build_input_key(source: dict, seed: dict, base_manifest_digest: str, *, generation: str = "primary") -> str:
    if generation not in {"primary", "cache-invalidation-probe"}:
        raise ProbeFailure("backend_build_generation_unsupported")
    identity = {"source_ref": source["source_ref"], "source": source["manifest_digest"],
        "recipe": source["recipe_digest"], "derived_project": source["derived_project_digest"],
        "seed": seed["manifest_digest"], "dependency_key": seed["cache_key"],
        "base_manifest": base_manifest_digest, "builder": TOOLCHAIN_DIGEST,
        "platform": "linux/amd64", "generation": generation}
    return digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))
