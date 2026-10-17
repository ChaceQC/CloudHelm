"""Copy the two verified fixed seeds into the admitted physical storage boundary."""

import os
import re
from pathlib import Path
from uuid import uuid4

from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at, read_regular, write_new_file
from packages.contracts.p1.npm_cache import NpmDownloadSpec, npm_seed_id

from .engineering_registry import NPM_DOWNLOAD_ROOT, NPM_MANIFEST
from .npm_download_io import NpmDownloadError
from .npm_downloads import NpmDownloadStore
from . import python_dependencies
from .toolchain import ProbeFailure, private_directory


def _copy(source: Path, target: Path):
    """The caller verified this fixed seed; pin every copied inode and bound bytes."""
    staged = target.parent / ("stage-" + uuid4().hex)
    private_directory(staged)
    origin, destination = PrivateRoot(source), PrivateRoot(staged)
    total, count = 0, 0
    try:
        for entry in sorted(source.rglob("*")):
            relative = str(entry.relative_to(source))
            if entry.is_dir():
                with directory_at(destination.fd, relative, create=True) as folder:
                    os.fchmod(folder, 0o700)
                continue
            raw = read_regular(origin.fd, relative, 128 * 1024**2)
            total, count = total + len(raw), count + 1
            if total > 256 * 1024**2 or count > 256:
                raise ProbeFailure("engineering_seed_copy_bound_exceeded")
            write_new_file(destination.fd, relative, raw, executable=relative == "uv")
            os.chmod(staged / relative, 0o500 if relative == "uv" else 0o400)
        for folder in sorted((path for path in staged.rglob("*") if path.is_dir()), reverse=True):
            folder.chmod(0o500)
        staged.chmod(0o500)
        os.rename(staged, target)
        parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        origin.close()
        destination.close()


def prepare_build_seeds(storage, *, backend_source):
    storage.observe()
    npm_spec = NpmDownloadSpec(project_id="reference-notes", trust_domain="controlled-development")
    source_root, npm = _find_npm_seed(npm_spec)
    npm_root = storage.cache_root / "npm"
    private_directory(npm_root)
    target = npm_root / npm_seed_id(npm_spec)
    if not target.exists():
        _copy(source_root / npm_seed_id(npm_spec), target)
    with NpmDownloadStore(npm_root) as copied:
        if copied.verify(npm_spec, expected_manifest_digest=NPM_MANIFEST) != npm:
            raise ProbeFailure("engineering_npm_seed_copy_mismatch")
    inputs = python_dependencies.PythonDependencyInput()
    original = python_dependencies.CACHE_ROOT / inputs.cache_key
    python = python_dependencies.verify_seed(original, inputs, source_files=backend_source)
    python_root = storage.cache_root / "python"
    private_directory(python_root)
    target = python_root / inputs.cache_key
    if not target.exists():
        _copy(original, target)
    copied = python_dependencies.verify_admitted_seed(target, inputs, source_files=backend_source)
    if ({key: value for key, value in copied.items() if key != "path"}
            != {key: value for key, value in python.items() if key != "path"}):
        raise ProbeFailure("engineering_python_seed_copy_mismatch")
    storage.observe()
    return {"npm_root": npm_root, "npm_spec": npm_spec, "npm_manifest": NPM_MANIFEST,
            "python_root": target, "python_manifest": python["manifest_digest"]}


def _find_npm_seed(spec):
    """Resolve the fixed content reference; a previous probe UUID is not configuration."""
    root = PrivateRoot(NPM_DOWNLOAD_ROOT)
    try:
        names = os.listdir(root.fd)
        if len(names) > 128:
            raise ProbeFailure("engineering_npm_seed_catalog_bound_exceeded")
        for name in sorted(names):
            if not re.fullmatch(r"npm-check-[0-9a-f]{32}", name):
                continue
            candidate = NPM_DOWNLOAD_ROOT / name
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            cache = candidate / "cache"
            if cache.is_symlink() or not cache.is_dir():
                continue
            try:
                with NpmDownloadStore(cache) as store:
                    receipt = store.verify(spec, expected_manifest_digest=NPM_MANIFEST)
                return cache, receipt
            except (NpmDownloadError, WorkspaceFileError, OSError, ValueError):
                continue
    finally:
        root.close()
    raise ProbeFailure("engineering_fixed_npm_seed_unavailable")
