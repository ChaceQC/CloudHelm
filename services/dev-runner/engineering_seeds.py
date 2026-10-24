"""Copy the two verified fixed seeds into the admitted physical storage boundary."""

import os
import shutil
import stat
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

from modules.artifacts.content_files import publish_directory
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at, read_regular, write_new_file
from packages.contracts.p1.npm_cache import NpmDownloadSpec, npm_seed_id

from .engineering_registry import NPM_DOWNLOAD_ROOT
from .npm_download_io import NpmDownloadError
from .npm_downloads import NpmDownloadStore
from . import python_dependencies
from .toolchain import ProbeFailure, private_directory


def _copy(source: Path, target: Path):
    """The caller verified this fixed seed; pin every copied inode and bound bytes."""
    staged = target.parent / ("stage-" + uuid4().hex)
    private_directory(staged)
    origin, destination = None, None
    try:
        origin = PrivateRoot(source)
        destination = PrivateRoot(staged)
        total, count, pending = 0, 0, [""]
        while pending:
            folder = pending.pop()
            context = directory_at(origin.fd, folder) if folder else nullcontext(origin.fd)
            with context as source_fd:
                names = os.listdir(source_fd)
                count += len(names)
                if count > 256:
                    raise ProbeFailure("engineering_seed_copy_bound_exceeded")
                for name in sorted(names):
                    relative = folder + "/" + name if folder else name
                    state = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
                    if stat.S_ISDIR(state.st_mode):
                        if folder or state.st_mode & 0o222:
                            raise ProbeFailure("engineering_seed_copy_directory_invalid")
                        with directory_at(destination.fd, relative, create=True) as child:
                            os.fchmod(child, 0o700)
                        pending.append(relative)
                        continue
                    if not stat.S_ISREG(state.st_mode) or state.st_mode & 0o222:
                        raise ProbeFailure("engineering_seed_copy_file_invalid")
                    raw = read_regular(source_fd, name, 128 * 1024**2)
                    total += len(raw)
                    if total > 256 * 1024**2:
                        raise ProbeFailure("engineering_seed_copy_bound_exceeded")
                    write_new_file(destination.fd, relative, raw, executable=relative == "uv")
                    os.chmod(staged / relative, 0o500 if relative == "uv" else 0o400)
        for folder in sorted((path for path in staged.iterdir() if path.is_dir()), reverse=True):
            folder.chmod(0o500)
            with directory_at(destination.fd, folder.name) as descriptor:
                os.fsync(descriptor)
        staged.chmod(0o500)
        os.fsync(destination.fd)
        parent = PrivateRoot(target.parent)
        try:
            publish_directory(parent.fd, staged.name, target.name)
        finally:
            parent.close()
    finally:
        if origin is not None:
            origin.close()
        if destination is not None:
            destination.close()
        if staged.exists():
            staged.chmod(0o700)
            for child in staged.iterdir():
                if child.is_dir() and not child.is_symlink():
                    child.chmod(0o700)
            shutil.rmtree(staged)


def reference_npm_spec():
    return NpmDownloadSpec(project_id="reference-notes", trust_domain="controlled-development")


def read_npm_seed():
    """Offline resolution of one registered identity, without directory discovery."""
    spec = reference_npm_spec()
    if not os.path.lexists(NPM_DOWNLOAD_ROOT / npm_seed_id(spec)):
        raise ProbeFailure("engineering_npm_seed_unavailable")
    try:
        with NpmDownloadStore(NPM_DOWNLOAD_ROOT) as store:
            return store.verify(spec)
    except (NpmDownloadError, WorkspaceFileError, OSError, ValueError):
        raise ProbeFailure("engineering_npm_seed_invalid") from None


def prepare_build_seeds(storage, *, backend_source):
    """Copy verified registered content under admission; never acquire downloads."""
    storage.observe()
    npm_spec, npm = reference_npm_spec(), read_npm_seed()
    npm_root = storage.cache_root / "npm"
    private_directory(npm_root)
    target = npm_root / npm_seed_id(npm_spec)
    with NpmDownloadStore(npm_root) as copied:
        with copied.root.exclusive():
            if not os.path.lexists(target):
                _copy(NPM_DOWNLOAD_ROOT / npm_seed_id(npm_spec), target)
        retained = copied.verify(npm_spec)
    # Acquisition time is provenance; immutable content and the fixed spec must match.
    if (retained.manifest.model_dump(exclude={"created_at"})
            != npm.manifest.model_dump(exclude={"created_at"})):
        raise ProbeFailure("engineering_npm_seed_copy_mismatch")
    inputs = python_dependencies.PythonDependencyInput()
    original = python_dependencies.CACHE_ROOT / inputs.cache_key
    python = python_dependencies.verify_seed(original, inputs, source_files=backend_source)
    python_root = storage.cache_root / "python"
    private_directory(python_root)
    target = python_root / inputs.cache_key
    root = PrivateRoot(python_root)
    try:
        with root.exclusive():
            if not os.path.lexists(target):
                _copy(original, target)
    finally:
        root.close()
    copied = python_dependencies.verify_admitted_seed(target, inputs, source_files=backend_source)
    if ({key: value for key, value in copied.items() if key != "path"}
            != {key: value for key, value in python.items() if key != "path"}):
        raise ProbeFailure("engineering_python_seed_copy_mismatch")
    storage.observe()
    return {"npm_root": npm_root, "npm_spec": npm_spec, "npm_manifest": retained.manifest_digest,
            "python_root": target, "python_manifest": python["manifest_digest"]}
