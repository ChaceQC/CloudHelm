"""Prepare immutable Workspace dependency snapshots for an exec-enabled runtime tmpfs."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import tarfile
import time
from dataclasses import dataclass
from email.errors import MessageError
from email import message_from_bytes
from pathlib import Path, PurePosixPath
from uuid import uuid4

from modules.workspaces.safe_paths import (
    PrivateRoot, directory_at, read_regular, remove_staging, write_new_file,
)
from packages.contracts.p1.workspace_git import WorkspaceBinding

from . import development_storage, python_dependencies
from .offline_images import SOURCE_REFERENCE
from .toolchain import DOCKER, ProbeFailure, private_directory, safe_diagnostic
from modules.execution.docker_endpoint import socket_path
from .workspace_development_inputs import (
    METHOD, WORKSPACE_PYTHON_TOOLCHAIN, WorkspaceDependencyInputs, WorkspacePythonToolchain,
    WORKSPACE_INSTALL_ENVIRONMENT, WORKSPACE_INSTALL_WORKDIR,
    read_workspace_backend_inputs, validate_workspace_dependency_inputs,
)

SCOPE = "cloudhelm-p1-workspace-python-dependencies"
MEMORY_BYTES, CPU_QUOTA, CPU_PERIOD, PIDS_LIMIT = 768 * 1024**2, 150000, 100000, 128
ENVIRONMENT_BYTES, TOOL_EXEC_BYTES = 384 * 1024**2, 80 * 1024**2
INSTALL_CACHE_BYTES, INSTALL_TEMP_BYTES, OUTPUT_BYTES, SHM_BYTES = (
    256 * 1024**2, 64 * 1024**2, 192 * 1024**2, 8 * 1024**2)
WORKSPACE_SYNC_ARGUMENTS = tuple(python_dependencies.SYNC_ARGUMENTS)
MAX_ARCHIVE_BYTES, MAX_ENVIRONMENT_BYTES, MAX_ARCHIVE_MEMBERS = OUTPUT_BYTES, ENVIRONMENT_BYTES, 100000
MAX_METADATA_BYTES = 1024**2
ARCHIVE_NAME = "dependencies.tar.gz"
EXPECTED_TOP_LEVEL = {"bin", "lib", "pyvenv.cfg"}
INSTALL_TMPFS_BYTES = {"/environment": ENVIRONMENT_BYTES, "/probe/tooling": TOOL_EXEC_BYTES,
    "/private-cache": INSTALL_CACHE_BYTES, "/tmp": INSTALL_TEMP_BYTES,
    "/probe/output": OUTPUT_BYTES, "/dev/shm": SHM_BYTES}
ABSOLUTE_PYTHON_LINKS = {
    "/usr/local/bin/python", "/usr/local/bin/python3", "/usr/local/bin/python3.12",
}

CHECK_DISTRIBUTIONS = (
    "import importlib.metadata as m, json, re, sys, psycopg; "
    "normalize=lambda value: re.sub(r'[-_.]+','-',value).lower(); "
    "actual={normalize(item.metadata['Name']):item.version for item in m.distributions()}; "
    "expected=json.load(open('/snapshot/expected-distributions.json',encoding='utf-8')); "
    "assert sys.version_info[:3] == (3,12,13); "
    "assert sys.prefix == '/environment'; "
    "assert actual == expected; "
    "assert psycopg.pq.__impl__ == 'binary'; "
    "print(json.dumps({'python':'3.12.13','distributions':actual,'psycopg_impl':'binary'},"
    "sort_keys=True,separators=(',',':')))"
)

CONTAINER_SCRIPT = r'''
import hashlib, json, os, shutil, stat, subprocess, sys, tarfile, tomllib, time
SYNC = %s
CHECK = %s
MAX_ARCHIVE = %d
MAX_BYTES = %d
MAX_MEMBERS = %d
ABSOLUTE_LINKS = %s
INSTALL_ENVIRONMENT = %s
INSTALL_WORKDIR = %s
TMPFS_LIMITS = %s

def fail(code):
    print("CLOUDHELM_WORKSPACE_DEPENDENCIES=" + code, flush=True)
    raise SystemExit(1)

mounts = {}
for line in open("/proc/self/mountinfo", encoding="utf-8"):
    parts = line.split(); split = parts.index("-")
    mounts[parts[4]] = parts[split + 1]
kernel_tmpfs = {}
for path, maximum in TMPFS_LIMITS.items():
    state = os.statvfs(path)
    size = state.f_blocks * state.f_frsize
    if mounts.get(path) != "tmpfs" or not 0 < size <= maximum or state.f_flag & os.ST_RDONLY:
        fail("kernel_tmpfs_boundary_mismatch")
    kernel_tmpfs[path] = size

def safe_link(name, target):
    if target in ABSOLUTE_LINKS and name in {"bin/python", "bin/python3", "bin/python3.12"}:
        return True
    if not target or target.startswith("/") or "\\" in target or "\x00" in target:
        return False
    resolved = os.path.normpath(os.path.join(os.path.dirname(name), target))
    return resolved not in {".", ".."} and not resolved.startswith("../")

def add_tree(archive, root):
    total, count, names = 0, 0, set()
    pending = [("", root)]
    while pending:
        prefix, directory = pending.pop()
        entries = sorted(os.scandir(directory), key=lambda item: item.name, reverse=True)
        for entry in entries:
            name = prefix + entry.name
            if (name in names or name.startswith("/") or "\x00" in name
                    or any(part in {"", ".", ".."} for part in name.split("/"))):
                fail("archive_path_invalid")
            names.add(name)
            count += 1
            if count > MAX_MEMBERS:
                fail("archive_member_limit")
            info = os.stat(entry.path, follow_symlinks=False)
            item = tarfile.TarInfo(name)
            if stat.S_ISDIR(info.st_mode):
                item.type, item.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(item)
                pending.append((name + "/", entry.path))
            elif stat.S_ISREG(info.st_mode):
                mode = stat.S_IMODE(info.st_mode)
                if mode & 0o7000:
                    fail("archive_file_mode_invalid")
                total += info.st_size
                if total > MAX_BYTES:
                    fail("archive_unpacked_size_limit")
                item.size, item.mode = info.st_size, 0o755 if mode & 0o111 else 0o644
                descriptor = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(descriptor, "rb") as stream:
                    if os.fstat(stream.fileno()).st_ino != info.st_ino:
                        fail("archive_file_changed")
                    archive.addfile(item, stream)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(entry.path)
                if not safe_link(name, target):
                    fail("archive_symlink_invalid")
                item.type, item.mode, item.linkname = tarfile.SYMTYPE, 0o777, target
                archive.addfile(item)
            else:
                fail("archive_member_type_invalid")
    return count, total

uv_path = "/probe/tooling/uv"
uv_digest = sys.argv[2]
shutil.copyfile("/probe/python-seed/uv", uv_path)
os.chmod(uv_path, 0o500)
digest = hashlib.sha256()
with open(uv_path, "rb") as stream:
    while block := stream.read(1024 * 1024):
        digest.update(block)
if "sha256:" + digest.hexdigest() != uv_digest:
    fail("uv_binary_digest_mismatch")
version = subprocess.run([uv_path, "--version"], capture_output=True,
    text=True, encoding="utf-8", check=False, timeout=10)
if version.returncode or version.stdout.strip().split()[:2] != ["uv", "0.11.29"]:
    fail("uv_version_mismatch")
project = "/private-cache/project"
os.mkdir(project, 0o700)
shutil.copyfile("/snapshot/derived-pyproject.toml", project + "/pyproject.toml")
shutil.copyfile("/snapshot/.python-version", project + "/.python-version")
locked = subprocess.run([uv_path, "lock", "--offline", "--no-build", "--no-index",
    "--find-links=/wheelhouse", "--python=/usr/local/bin/python", "--no-python-downloads"],
    cwd=project, env=INSTALL_ENVIRONMENT, stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=False, timeout=60)
if locked.returncode:
    print("CLOUDHELM_WORKSPACE_INSTALL_DIAGNOSTIC=" + locked.stderr[-600:].replace("\n", " "), flush=True)
    fail("offline_lock_failed")
expected = json.load(open("/snapshot/expected-distributions.json", encoding="utf-8"))
packages = tomllib.load(open(project + "/uv.lock", "rb"))["package"]
external = [item for item in packages if item.get("source") != {"virtual": "."}]
if (len(external) != len(expected) or {item["name"]:item["version"] for item in external} != expected
    or any(item.get("sdist") or item.get("source") != {"registry":"/wheelhouse"} for item in external)):
    fail("offline_lock_distribution_drift")
installed = subprocess.run([uv_path, *SYNC], cwd=project,
    env=INSTALL_ENVIRONMENT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.PIPE, text=True, encoding="utf-8", check=False, timeout=180)
if installed.returncode:
    print("CLOUDHELM_WORKSPACE_INSTALL_DIAGNOSTIC=" + installed.stderr[-600:].replace("\n", " "), flush=True)
    fail("uv_sync_failed")
checked = subprocess.run(["/environment/bin/python", "-B", "-I", "-c", CHECK],
    stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
    check=False, timeout=30)
if checked.returncode:
    fail("installed_distribution_check_failed")
try:
    result = json.loads(checked.stdout)
except ValueError:
    fail("installed_distribution_output_invalid")
expected = json.load(open("/snapshot/expected-distributions.json", encoding="utf-8"))
if (result.get("python") != "3.12.13" or result.get("psycopg_impl") != "binary"
        or result.get("distributions") != expected):
    fail("installed_distribution_mismatch")
archive_path = "/probe/output/" + "dependencies.tar.gz"
try:
    with tarfile.open(archive_path, "w:gz", compresslevel=6) as archive:
        members, unpacked = add_tree(archive, "/environment")
except SystemExit:
    raise
except Exception:
    fail("archive_creation_failed")
archive_size = os.stat(archive_path, follow_symlinks=False).st_size
if not 0 < archive_size <= MAX_ARCHIVE:
    fail("archive_size_limit")
print("CLOUDHELM_WORKSPACE_DEPENDENCIES=" + json.dumps({
    "python": "3.12.13", "uv": "0.11.29", "distributions": result["distributions"],
    "psycopg_impl": "binary", "archive_bytes": archive_size,
    "archive_members": members, "archive_unpacked_bytes": unpacked,
    "kernel_tmpfs_bytes": kernel_tmpfs,
}, sort_keys=True, separators=(",", ":")), flush=True)
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    time.sleep(0.2)
''' % (
    repr(list(WORKSPACE_SYNC_ARGUMENTS)),
    repr(CHECK_DISTRIBUTIONS),
    MAX_ARCHIVE_BYTES,
    MAX_ENVIRONMENT_BYTES,
    MAX_ARCHIVE_MEMBERS,
    repr(sorted(ABSOLUTE_PYTHON_LINKS)),
    repr(dict(WORKSPACE_INSTALL_ENVIRONMENT)),
    repr(WORKSPACE_INSTALL_WORKDIR),
    repr(INSTALL_TMPFS_BYTES),
)


@dataclass(frozen=True)
class WorkspaceDependencyReceipt:
    binding: WorkspaceBinding
    environment_key: str
    dependency_directory: Path
    snapshot_path: Path
    snapshot_digest: str
    snapshot_bytes: int
    toolchain_digest: str
    dependency_cache_key: str
    seed_manifest_digest: str
    lock_digest: str
    project_digest: str
    python: str
    uv: str
    platform: str
    distributions: tuple[tuple[str, str], ...]
    archive_member_count: int
    archive_expanded_bytes: int
    reused: bool
    verified: bool = True

    def model_dump(self, *, mode: str = "python") -> dict:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__}
        value["dependency_directory"] = str(self.dependency_directory)
        value["snapshot_path"] = str(self.snapshot_path)
        value["binding"] = self.binding.model_dump(mode="json" if mode == "json" else "python")
        value["distributions"] = dict(self.distributions)
        return value


class _InstallFailure(ProbeFailure):
    def __init__(self, category: str, *, safe_to_remove_stage: bool, diagnostic: str = "") -> None:
        super().__init__(category, detail=diagnostic)
        self.safe_to_remove_stage = safe_to_remove_stage


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _require_storage(storage) -> str:
    try:
        storage.observe()
        admission = storage.admission
        snapshot, registration = admission.snapshot, admission.snapshot.registration
        storage_id = registration.storage_id
        if (os.getuid() != development_storage.UID or snapshot.purpose != "workspace"
                or registration.scope != "local_controlled_development"
                or not {"workspace", "cache"}.issubset(registration.allowed_purposes)
                or not {"rw", "nosuid", "nodev", "noexec"}.issubset(snapshot.mount_options)):
            raise ProbeFailure("workspace_python_storage_scope_or_mount_unsupported")
        data = admission.directory.parent
        if (Path(storage.workspace_root) != data / "workspace"
                or Path(storage.cache_root) != data / "cache"
                or os.stat(storage.workspace_root).st_dev != os.fstat(admission.directory_fd).st_dev
                or os.stat(storage.cache_root).st_dev != os.fstat(admission.directory_fd).st_dev):
            raise ProbeFailure("workspace_python_storage_root_mismatch")
        return storage_id
    except ProbeFailure:
        raise
    except (OSError, AttributeError, TypeError):
        raise ProbeFailure("workspace_python_storage_admission_required") from None


def _fixed_cgroup_parent(storage_id: str, value: str) -> None:
    from .resource_context import current_group

    group = current_group()
    if group is not None and group.registration.storage.storage_id == storage_id and value == group.unit:
        group.observe()
        return
    raise ProbeFailure("workspace_python_legacy_start_retired")


def _private_storage_directory(path: Path, *, device: int) -> None:
    private_directory(path)
    state = path.lstat()
    if state.st_dev != device:
        raise ProbeFailure("workspace_python_storage_device_mismatch")


def _identity_present(client, workspace_key: str, operation_id: str | None = None) -> bool:
    args = ["ps", "--all", "--quiet", "--filter", f"label=cloudhelm.scope={SCOPE}",
            "--filter", f"label=cloudhelm.workspace_key={workspace_key}"]
    if operation_id is not None:
        args += ["--filter", f"label=cloudhelm.operation_id={operation_id}"]
    return bool(client.run(*args, timeout=15).stdout.strip())


def _verify_base_image(client, toolchain: WorkspacePythonToolchain) -> str:
    present = client.run("image", "inspect", toolchain.python_image_reference, "--format", "{{.Id}}",
                         required=False)
    if present.returncode:
        client.run("pull", "--platform=linux/amd64", toolchain.python_image_reference, timeout=240)
    descriptor = client.run("image", "inspect", toolchain.python_image_reference, "--format",
                            "{{json .Descriptor}}")
    image = client.run("image", "inspect", toolchain.python_image_reference, "--format",
                       "{{json .Id}} {{json .Os}} {{json .Architecture}}")
    try:
        actual_descriptor = json.loads(descriptor.stdout)
        values = image.stdout.strip().split()
        image_id, operating_system, architecture = (json.loads(item) for item in values)
    except (ValueError, TypeError):
        raise ProbeFailure("workspace_python_base_image_observation_invalid") from None
    if (actual_descriptor.get("digest") != toolchain.python_image_digest
            or (operating_system, architecture) != ("linux", "amd64")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)):
        raise ProbeFailure("workspace_python_base_image_identity_mismatch")
    return image_id


def _verified_uv_binary_digest(seed: Path) -> str:
    root = PrivateRoot(seed)
    try:
        manifest = json.loads(read_regular(root.fd, "manifest.json", MAX_METADATA_BYTES).decode("utf-8"))
        digest = manifest["uv_binary"]["hash"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("invalid_digest")
        return digest
    except (OSError, ValueError, KeyError, TypeError):
        raise ProbeFailure("workspace_python_seed_manifest_invalid") from None
    finally:
        root.close()


def _read_snapshot(root: int, inputs: WorkspaceDependencyInputs) -> None:
    expected = {"pyproject.toml": inputs.pyproject_bytes, "uv.lock": inputs.lock_bytes,
        "derived-pyproject.toml": python_dependencies.derived_project(),
        ".python-version": inputs.python_pin_bytes,
        "expected-distributions.json": _json_bytes(dict(inputs.distributions))}
    with directory_at(root, "inputs") as snapshot:
        if set(os.listdir(snapshot)) != set(expected):
            raise ProbeFailure("workspace_python_input_snapshot_members_mismatch")
        for name, content in expected.items():
            if read_regular(snapshot, name, max(len(content), MAX_METADATA_BYTES)) != content:
                raise ProbeFailure("workspace_python_input_snapshot_mismatch")


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _member_name(item: tarfile.TarInfo) -> str:
    name = item.name[:-1] if item.isdir() and item.name.endswith("/") else item.name
    if (not name or name.startswith("/") or "\x00" in name or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ProbeFailure("workspace_python_archive_path_invalid")
    return name


def _symlink_safe(name: str, target: str) -> bool:
    if name in {"bin/python", "bin/python3", "bin/python3.12"} and target in ABSOLUTE_PYTHON_LINKS:
        return True
    if not target or target.startswith("/") or "\\" in target or "\x00" in target:
        return False
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    return resolved not in {".", ".."} and not resolved.startswith("../")


def _archive_distributions(archive: tarfile.TarFile, expected: dict[str, str]) -> tuple[int, int]:
    members = archive.getmembers()
    if not members or len(members) > MAX_ARCHIVE_MEMBERS:
        raise ProbeFailure("workspace_python_archive_member_count_invalid")
    names, directories, files, symlinks, distributions = set(), set(), set(), set(), {}
    metadata_members, unpacked = [], 0
    for item in members:
        name = _member_name(item)
        if name in names or item.mode & 0o7000:
            raise ProbeFailure("workspace_python_archive_member_identity_invalid")
        names.add(name)
        if item.isdir():
            if item.mode != 0o755 or item.size != 0:
                raise ProbeFailure("workspace_python_archive_directory_invalid")
            directories.add(name)
        elif item.isfile():
            if item.mode not in {0o644, 0o755}:
                raise ProbeFailure("workspace_python_archive_file_mode_invalid")
            unpacked += item.size
            if unpacked > MAX_ENVIRONMENT_BYTES:
                raise ProbeFailure("workspace_python_archive_expanded_size_limit")
            files.add(name)
            if name.endswith(".dist-info/METADATA"):
                metadata_members.append(item)
        elif item.issym():
            if item.mode != 0o777 or not _symlink_safe(name, item.linkname):
                raise ProbeFailure("workspace_python_archive_symlink_invalid")
            symlinks.add(name)
        else:
            raise ProbeFailure("workspace_python_archive_member_type_unsupported")
    for name in names:
        parent = PurePosixPath(name).parent
        while str(parent) != ".":
            if str(parent) in symlinks:
                raise ProbeFailure("workspace_python_archive_symlink_parent_invalid")
            parent = parent.parent
    if (not EXPECTED_TOP_LEVEL.issubset(names)
            or not {"lib", "lib/python3.12", "lib/python3.12/site-packages"}.issubset(directories)
            or "pyvenv.cfg" not in files
            or not {"bin/python"}.issubset(files | symlinks)):
        raise ProbeFailure("workspace_python_archive_layout_invalid")
    if len(metadata_members) > 256:
        raise ProbeFailure("workspace_python_distribution_metadata_count_exceeded")
    for item in metadata_members:
        if item.size > MAX_METADATA_BYTES:
            raise ProbeFailure("workspace_python_distribution_metadata_exceeded")
        stream = archive.extractfile(item)
        if stream is None:
            raise ProbeFailure("workspace_python_distribution_metadata_invalid")
        metadata = message_from_bytes(stream.read(MAX_METADATA_BYTES + 1))
        name, version = metadata.get("Name"), metadata.get("Version")
        if not name or not version:
            raise ProbeFailure("workspace_python_distribution_metadata_invalid")
        normalized = _normalized_name(name)
        if normalized in distributions:
            raise ProbeFailure("workspace_python_distribution_duplicate")
        distributions[normalized] = version
    if distributions != expected:
        raise ProbeFailure("workspace_python_distribution_set_mismatch")
    config = archive.extractfile("pyvenv.cfg")
    values = {} if config is None else dict(
        (key.strip(), value.strip()) for line in config.read(4097).decode("utf-8", errors="strict").splitlines()
        if "=" in line for key, value in (line.split("=", 1),)
    )
    if values.get("version_info", values.get("version")) != "3.12.13":
        raise ProbeFailure("workspace_python_venv_python_version_mismatch")
    return len(members), unpacked


def _verify_archive(path: Path, expected_digest: str, expected_size: int,
                    distributions: tuple[tuple[str, str], ...]) -> tuple[int, int]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_mode & 0o222 or before.st_nlink != 1
                or before.st_size != expected_size or not 0 < before.st_size <= MAX_ARCHIVE_BYTES):
            raise ProbeFailure("workspace_python_archive_file_boundary_invalid")
        digest = hashlib.sha256()
        while block := os.read(descriptor, 1024**2):
            digest.update(block)
        if "sha256:" + digest.hexdigest() != expected_digest:
            raise ProbeFailure("workspace_python_archive_digest_mismatch")
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "rb") as stream, tarfile.open(fileobj=stream, mode="r:gz") as archive:
            result = _archive_distributions(archive, dict(distributions))
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ProbeFailure("workspace_python_archive_changed_during_verify")
        return result
    except ProbeFailure:
        raise
    except (OSError, tarfile.TarError, UnicodeError, ValueError, MessageError):
        raise ProbeFailure("workspace_python_archive_invalid") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_snapshot(stage_root: int, inputs: WorkspaceDependencyInputs) -> None:
    files = {"pyproject.toml": inputs.pyproject_bytes, "uv.lock": inputs.lock_bytes,
        "derived-pyproject.toml": python_dependencies.derived_project(),
        ".python-version": inputs.python_pin_bytes,
        "expected-distributions.json": _json_bytes(dict(inputs.distributions))}
    with directory_at(stage_root, "inputs", create=True) as input_root:
        os.fchmod(input_root, 0o700)
        for name, content in files.items():
            write_new_file(input_root, name, content)
            descriptor = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=input_root)
            try:
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(input_root)
        os.fchmod(input_root, 0o500)


def _require_live_source(storage, binding: WorkspaceBinding, inputs: WorkspaceDependencyInputs) -> None:
    current = read_workspace_backend_inputs(storage, binding)
    expected = {"pyproject.toml": inputs.pyproject_bytes, "uv.lock": inputs.lock_bytes,
        ".python-version": inputs.python_pin_bytes}
    if current != expected:
        raise ProbeFailure("workspace_python_source_changed_during_prepare")


def _container_mounts(stage: Path, seed: Path) -> dict[str, tuple[str, bool]]:
    return {"/snapshot": (str(stage / "inputs"), True),
        "/probe/python-seed": (str(seed), True), "/wheelhouse": (str(seed / "wheels"), True)}


def _validate_container(metadata: dict, *, operation_id: str, workspace_key: str, image_id: str,
                        stage: Path, seed: Path, cgroup_parent: str) -> None:
    config, host = metadata["Config"], metadata["HostConfig"]
    labels = config.get("Labels") or {}
    expected_binds = _container_mounts(stage, seed)
    binds = {item["Destination"]: (item["Source"], not item["RW"])
        for item in metadata["Mounts"] if item["Type"] == "bind"}
    actual_binds = {name: (str(Path(source).resolve(strict=True)), readonly)
        for name, (source, readonly) in expected_binds.items()}
    tmpfs = {"/environment": f"rw,nosuid,nodev,exec,size={ENVIRONMENT_BYTES},uid=1000,gid=1000,mode=0700",
        "/probe/tooling": f"rw,nosuid,nodev,exec,size={TOOL_EXEC_BYTES},uid=1000,gid=1000,mode=0700",
        "/private-cache": f"rw,nosuid,nodev,noexec,size={INSTALL_CACHE_BYTES},uid=1000,gid=1000,mode=0700",
        "/tmp": f"rw,nosuid,nodev,noexec,size={INSTALL_TEMP_BYTES},uid=1000,gid=1000,mode=1777",
        "/probe/output": f"rw,nosuid,nodev,noexec,size={OUTPUT_BYTES},uid=1000,gid=1000,mode=0700"}
    actual_tmpfs = {item["Destination"] for item in metadata["Mounts"] if item["Type"] == "tmpfs"}
    state = metadata["State"]
    checks = {
        "labels": labels.get("cloudhelm.scope") == SCOPE and labels.get("cloudhelm.method") == METHOD
            and labels.get("cloudhelm.operation_id") == operation_id
            and labels.get("cloudhelm.workspace_key") == workspace_key,
        "image": metadata["Image"] == image_id and config.get("Image") == SOURCE_REFERENCE,
        "identity": config.get("User") == "1000:1000" and config.get("Tty") is False,
        "readonly": host.get("ReadonlyRootfs") is True and host.get("Privileged") is not True,
        "network": host.get("NetworkMode") == "none" and not host.get("PortBindings"),
        "cgroup": host.get("CgroupParent") == cgroup_parent,
        "limits": host.get("Memory") == MEMORY_BYTES and host.get("MemorySwap") == MEMORY_BYTES
            and host.get("CpuPeriod") == CPU_PERIOD and host.get("CpuQuota") == CPU_QUOTA
            and host.get("PidsLimit") == PIDS_LIMIT,
        "privileges": set(host.get("CapDrop") or []) == {"ALL"} and not host.get("CapAdd")
            and not host.get("Devices") and host.get("SecurityOpt") == ["no-new-privileges:true"],
        "tmpfs": host.get("Tmpfs") == tmpfs and host.get("ShmSize") == SHM_BYTES,
        "binds": binds == actual_binds and len(binds) == 3,
        "logs": host.get("LogConfig", {}).get("Type") == "local",
        "running": state.get("Running") is True and state.get("Status") == "running",
    }
    if not all(checks.values()):
        raise ProbeFailure("workspace_python_container_boundary_mismatch",
            ",".join(name for name, passed in checks.items() if not passed),
            json.dumps({"tmpfs": host.get("Tmpfs"), "destinations": sorted(actual_tmpfs),
                        "shm_bytes": host.get("ShmSize")}) if not checks["tmpfs"] else "")


def _container_metadata(client, container_id: str) -> dict:
    try:
        values = json.loads(client.run("inspect", container_id, timeout=15).stdout)
        if len(values) != 1:
            raise ValueError("not_unique")
        return values[0]
    except (ValueError, TypeError, KeyError):
        raise ProbeFailure("workspace_python_container_identity_unavailable") from None


def _stop_and_remove(client, container_id: str, operation_id: str, workspace_key: str) -> None:
    metadata = _container_metadata(client, container_id)
    labels = metadata.get("Config", {}).get("Labels") or {}
    if (labels.get("cloudhelm.scope") != SCOPE or labels.get("cloudhelm.method") != METHOD
            or labels.get("cloudhelm.operation_id") != operation_id
            or labels.get("cloudhelm.workspace_key") != workspace_key):
        raise ProbeFailure("workspace_python_container_ownership_mismatch")
    if metadata.get("State", {}).get("Running"):
        client.run("stop", "--time=10", container_id, timeout=15)
    stopped = _container_metadata(client, container_id)
    if stopped.get("State", {}).get("Running") or stopped.get("State", {}).get("Status") not in {
            "created", "exited", "dead"}:
        raise ProbeFailure("workspace_python_container_stop_unconfirmed")
    client.run("rm", container_id, timeout=15)
    if _identity_present(client, workspace_key, operation_id):
        raise ProbeFailure("workspace_python_container_removal_unconfirmed")


def _collect_archive(client, container_id: str, target: Path, expected_size: int) -> None:
    if type(expected_size) is not int or not 0 < expected_size <= MAX_ARCHIVE_BYTES:
        raise ProbeFailure("workspace_python_archive_size_invalid")
    program = (
        "import os,stat,sys; p='/probe/output/dependencies.tar.gz'; "
        "fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW); s=os.fstat(fd); n=int(sys.argv[1]); "
        "assert stat.S_ISREG(s.st_mode) and s.st_size==n; "
        "data=os.read(fd,n+1); assert len(data)==n; sys.stdout.buffer.write(data)"
    )
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        result = subprocess.run([DOCKER, "--host", "unix://" + socket_path(), "exec", container_id,
            "/usr/local/bin/python", "-B", "-I", "-c", program, str(expected_size)],
            stdin=subprocess.DEVNULL, stdout=descriptor, stderr=subprocess.PIPE, timeout=90, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                 "DOCKER_CONFIG": str(client.config_directory)})
        if result.returncode or os.fstat(descriptor).st_size != expected_size:
            raise ProbeFailure("workspace_python_archive_collection_failed")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _run_install(client, *, operation_id: str, workspace_key: str, image_id: str, stage: Path,
                 seed: Path, archive_path: Path, cgroup_parent: str, uv_binary_digest: str) -> dict:
    if _identity_present(client, workspace_key):
        raise _InstallFailure("workspace_python_previous_execution_requires_reconciliation",
                              safe_to_remove_stage=False)
    container_id, failure, unresolved, result = None, None, False, None
    diagnostic = ""
    try:
        args = ["create", "--name", "cloudhelm-" + operation_id,
            "--label", f"cloudhelm.scope={SCOPE}", "--label", f"cloudhelm.method={METHOD}",
            "--label", f"cloudhelm.operation_id={operation_id}",
            "--label", f"cloudhelm.workspace_key={workspace_key}", "--pull=never",
            "--platform=linux/amd64", "--network=none", "--user=1000:1000", "--read-only",
            "--cgroup-parent=" + cgroup_parent, f"--memory={MEMORY_BYTES}",
            f"--memory-swap={MEMORY_BYTES}", f"--cpu-period={CPU_PERIOD}",
            f"--cpu-quota={CPU_QUOTA}", f"--pids-limit={PIDS_LIMIT}", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--ipc=private", f"--shm-size={SHM_BYTES}",
            "--log-driver=local", "--log-opt=max-size=1m", "--log-opt=max-file=1", "--log-opt=compress=false"]
        for destination, (source, readonly) in _container_mounts(stage, seed).items():
            suffix = ",readonly" if readonly else ""
            args += ["--mount", f"type=bind,src={source},dst={destination}{suffix},bind-propagation=rprivate"]
        for path, (size, mode, execute) in (
                ("/environment", (ENVIRONMENT_BYTES, "0700", True)),
                ("/probe/tooling", (TOOL_EXEC_BYTES, "0700", True)),
                ("/private-cache", (INSTALL_CACHE_BYTES, "0700", False)),
                ("/tmp", (INSTALL_TEMP_BYTES, "1777", False)),
                ("/probe/output", (OUTPUT_BYTES, "0700", False))):
            flag = "exec" if execute else "noexec"
            args += ["--tmpfs", f"{path}:rw,nosuid,nodev,{flag},size={size},uid=1000,gid=1000,mode={mode}"]
        args += ["--workdir=" + WORKSPACE_INSTALL_WORKDIR, "--entrypoint=/usr/local/bin/python", SOURCE_REFERENCE,
                 "-B", "-I", "-c", CONTAINER_SCRIPT, "install", uv_binary_digest]
        created = client.run(*args, timeout=30)
        candidate = created.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", candidate):
            failure = "workspace_python_container_identity_unavailable"
        else:
            container_id = candidate
            client.run("start", container_id, timeout=30)
            deadline = time.monotonic() + 210
            while time.monotonic() < deadline:
                output = client.run("logs", container_id, timeout=20).stdout
                details = [line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("CLOUDHELM_WORKSPACE_INSTALL_DIAGNOSTIC=")]
                diagnostic = safe_diagnostic(details[-1]) if details else ""
                matches = [line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("CLOUDHELM_WORKSPACE_DEPENDENCIES=")]
                if matches:
                    if len(matches) != 1:
                        failure = "workspace_python_install_result_invalid"
                        break
                    try:
                        result = json.loads(matches[0])
                    except ValueError:
                        failure = ("workspace_python_" + matches[0]
                                   if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", matches[0])
                                   else "workspace_python_install_result_invalid")
                    break
                if not _container_metadata(client, container_id)["State"].get("Running"):
                    failure = "workspace_python_install_failed"
                    break
                time.sleep(0.1)
            if failure is None and result is not None:
                metadata = _container_metadata(client, container_id)
                _validate_container(metadata, operation_id=operation_id, workspace_key=workspace_key,
                    image_id=image_id, stage=stage, seed=seed, cgroup_parent=cgroup_parent)
                _collect_archive(client, container_id, archive_path, result.get("archive_bytes"))
    except _InstallFailure as error:
        unresolved, failure = not error.safe_to_remove_stage, error.category
    except ProbeFailure as error:
        failure = error.category
        diagnostic = error.detail or error.diagnostic
    except Exception:
        failure = "workspace_python_install_container_failed"
    finally:
        if container_id is not None:
            try:
                _stop_and_remove(client, container_id, operation_id, workspace_key)
            except ProbeFailure:
                unresolved = True
        else:
            try:
                unresolved = _identity_present(client, workspace_key, operation_id)
            except ProbeFailure:
                unresolved = True
    if unresolved:
        raise _InstallFailure("workspace_python_container_stop_unconfirmed", safe_to_remove_stage=False)
    if failure is not None or result is None:
        raise _InstallFailure(failure or "workspace_python_install_failed", safe_to_remove_stage=True, diagnostic=diagnostic)
    return result


def _protect_archive(path: Path) -> tuple[str, int]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        state = os.fstat(descriptor)
        if (not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid()
                or state.st_nlink != 1 or state.st_size <= 0 or state.st_size > MAX_ARCHIVE_BYTES):
            raise ProbeFailure("workspace_python_archive_file_boundary_invalid")
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        digest = hashlib.sha256()
        while block := os.read(descriptor, 1024**2):
            digest.update(block)
        return "sha256:" + digest.hexdigest(), state.st_size
    except ProbeFailure:
        raise
    except OSError:
        raise ProbeFailure("workspace_python_archive_file_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _persistent_receipt(inputs: WorkspaceDependencyInputs, archive_digest: str, archive_size: int,
                        members: int, unpacked: int) -> dict:
    return {"schema_revision": "p1-workspace-python-dependencies-r1",
        "environment_key": inputs.environment_key, "identity": inputs.identity(),
        "archive_name": ARCHIVE_NAME, "snapshot_digest": archive_digest, "snapshot_bytes": archive_size,
        "archive_member_count": members, "archive_expanded_bytes": unpacked}


def _receipt(binding: WorkspaceBinding, inputs: WorkspaceDependencyInputs, directory: Path,
             stored: dict, archive: tuple[int, int], *, reused: bool) -> WorkspaceDependencyReceipt:
    return WorkspaceDependencyReceipt(binding=binding, environment_key=inputs.environment_key,
        dependency_directory=directory, snapshot_path=directory / ARCHIVE_NAME,
        snapshot_digest=stored["snapshot_digest"], snapshot_bytes=stored["snapshot_bytes"],
        toolchain_digest=inputs.toolchain.digest, dependency_cache_key="sha256:" + inputs.environment_key,
        seed_manifest_digest=inputs.seed_manifest_digest, lock_digest=inputs.lock_digest,
        project_digest=inputs.project_digest, python=inputs.toolchain.python, uv=inputs.toolchain.uv,
        platform=inputs.toolchain.platform, distributions=inputs.distributions,
        archive_member_count=archive[0], archive_expanded_bytes=archive[1], reused=reused)


def _cached_receipt(binding: WorkspaceBinding, directory: Path, root: int,
                    inputs: WorkspaceDependencyInputs) -> WorkspaceDependencyReceipt:
    try:
        if set(os.listdir(root)) != {"inputs", ARCHIVE_NAME, "receipt.json"}:
            raise ProbeFailure("workspace_python_cache_members_mismatch")
        _read_snapshot(root, inputs)
        stored = json.loads(read_regular(root, "receipt.json", MAX_METADATA_BYTES).decode("utf-8"))
        if (stored.get("schema_revision") != "p1-workspace-python-dependencies-r1"
                or stored.get("environment_key") != inputs.environment_key
                or stored.get("identity") != inputs.identity()
                or stored.get("archive_name") != ARCHIVE_NAME):
            raise ProbeFailure("workspace_python_cache_identity_mismatch")
        archive = _verify_archive(directory / ARCHIVE_NAME, stored["snapshot_digest"],
                                  stored["snapshot_bytes"], inputs.distributions)
        if archive != (stored["archive_member_count"], stored["archive_expanded_bytes"]):
            raise ProbeFailure("workspace_python_archive_observation_mismatch")
        return _receipt(binding, inputs, directory, stored, archive, reused=True)
    except ProbeFailure:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ProbeFailure("workspace_python_cache_receipt_invalid") from None


def _complete_stage(binding: WorkspaceBinding, inputs: WorkspaceDependencyInputs, namespace: Path,
                    namespace_root: int, stage_name: str, stage_path: Path, result: dict) -> WorkspaceDependencyReceipt:
    archive_path = stage_path / ARCHIVE_NAME
    if (result.get("python") != inputs.toolchain.python or result.get("uv") != inputs.toolchain.uv
            or result.get("psycopg_impl") != "binary"
            or result.get("distributions") != dict(inputs.distributions)
            or result.get("archive_bytes") != archive_path.stat().st_size
            or result.get("kernel_tmpfs_bytes") != INSTALL_TMPFS_BYTES):
        raise ProbeFailure("workspace_python_install_result_mismatch")
    digest, size = _protect_archive(archive_path)
    archive = _verify_archive(archive_path, digest, size, inputs.distributions)
    if archive != (result.get("archive_members"), result.get("archive_unpacked_bytes")):
        raise ProbeFailure("workspace_python_archive_result_mismatch")
    stored = _persistent_receipt(inputs, digest, size, archive[0], archive[1])
    stage = PrivateRoot(stage_path)
    try:
        os.unlink("intent.json", dir_fd=stage.fd)
        write_new_file(stage.fd, "receipt.json", _json_bytes(stored))
        os.fsync(stage.fd)
    finally:
        stage.close()
    target = namespace / inputs.environment_key
    if os.path.lexists(target):
        raise ProbeFailure("workspace_python_cache_publish_conflict")
    os.rename(stage_name, inputs.environment_key, src_dir_fd=namespace_root, dst_dir_fd=namespace_root)
    os.fsync(namespace_root)
    return _receipt(binding, inputs, target, stored, archive, reused=False)


def _prepare_new_snapshot(binding: WorkspaceBinding, inputs: WorkspaceDependencyInputs, storage, *,
        docker_client, seed: Path, uv_binary_digest: str, image_id: str, cgroup_parent: str,
        namespace: Path, namespace_root: int) -> WorkspaceDependencyReceipt:
    operation_id, stage_name = "workspace-python-" + uuid4().hex, "stage-" + uuid4().hex
    os.mkdir(stage_name, 0o700, dir_fd=namespace_root)
    os.fsync(namespace_root)
    stage_path = namespace / stage_name
    stage_created, cleanup_safe = True, True
    try:
        stage = PrivateRoot(stage_path)
        try:
            _write_snapshot(stage.fd, inputs)
            intent = {"schema_revision": "p1-workspace-python-dependencies-r1",
                "environment_key": inputs.environment_key, "identity": inputs.identity(),
                "operation_id": operation_id, "state": "preparing"}
            write_new_file(stage.fd, "intent.json", _json_bytes(intent))
        finally:
            stage.close()
        cleanup_safe = False
        result = _run_install(docker_client, operation_id=operation_id,
            workspace_key=inputs.workspace_key, image_id=image_id, stage=stage_path, seed=seed,
            archive_path=stage_path / ARCHIVE_NAME, cgroup_parent=cgroup_parent,
            uv_binary_digest=uv_binary_digest)
        cleanup_safe = True
        _require_live_source(storage, binding, inputs)
        receipt = _complete_stage(binding, inputs, namespace, namespace_root, stage_name, stage_path, result)
        stage_created = False
        storage.observe()
        return receipt
    except _InstallFailure as failure:
        cleanup_safe = failure.safe_to_remove_stage
        raise
    finally:
        if stage_created and cleanup_safe:
            with directory_at(namespace_root, stage_name) as staged:
                if "inputs" in os.listdir(staged):
                    with directory_at(staged, "inputs") as controls:
                        os.fchmod(controls, 0o700)
            remove_staging(namespace_root, stage_name)


def prepare_workspace_dependencies(binding: WorkspaceBinding, storage, *,
        docker_client, cgroup_parent: str, dependency_input: python_dependencies.PythonDependencyInput | None = None,
        python_seed: Path | None = None,
        toolchain: WorkspacePythonToolchain = WORKSPACE_PYTHON_TOOLCHAIN) -> WorkspaceDependencyReceipt:
    """Install fixed backend dependencies offline and publish a noexec-safe archive.

    Call under the admitted storage context and caller-owned workspace EnvironmentGroup
    lock. This prepares dependencies only; it never starts the application or owns
    the Workspace environment lifecycle.
    """
    if type(binding) is not WorkspaceBinding:
        raise ProbeFailure("workspace_python_binding_invalid")
    toolchain.require_supported()
    dependency_input = dependency_input or python_dependencies.PythonDependencyInput()
    dependency_input.require_supported()
    storage_id = _require_storage(storage)
    _fixed_cgroup_parent(storage_id, cgroup_parent)
    if not callable(getattr(docker_client, "run", None)):
        raise ProbeFailure("workspace_python_docker_client_required")
    if python_seed is None:
        seed = python_dependencies.CACHE_ROOT / dependency_input.cache_key
        seed_receipt = python_dependencies.verify_seed(seed, dependency_input)
    else:
        seed = Path(python_seed)
        seed_receipt = python_dependencies.verify_admitted_seed(seed, dependency_input)
    source = read_workspace_backend_inputs(storage, binding)
    inputs = validate_workspace_dependency_inputs(binding, source, dependency_input=dependency_input,
        seed_receipt=seed_receipt, toolchain=toolchain)
    device = os.fstat(storage.admission.directory_fd).st_dev
    root_path = Path(storage.cache_root) / "workspace-python"
    _private_storage_directory(root_path, device=device)
    namespace = root_path / inputs.workspace_key
    _private_storage_directory(namespace, device=device)
    target = namespace / inputs.environment_key
    try:
        state = target.lstat()
    except FileNotFoundError:
        state = None
    if state is not None:
        if (not stat.S_ISDIR(state.st_mode) or state.st_uid != os.getuid()
                or state.st_mode & 0o077 or state.st_dev != device):
            raise ProbeFailure("workspace_python_cache_directory_invalid")
        cache = PrivateRoot(target)
        try:
            receipt = _cached_receipt(binding, target, cache.fd, inputs)
        finally:
            cache.close()
        _require_live_source(storage, binding, inputs)
        storage.observe()
        return receipt
    if storage.observe().allocatable_bytes < MAX_ARCHIVE_BYTES + 1024**2:
        raise ProbeFailure("workspace_python_storage_capacity_unavailable")
    image_id = _verify_base_image(docker_client, toolchain)
    uv_binary_digest = _verified_uv_binary_digest(seed)
    namespace_root = PrivateRoot(namespace)
    try:
        return _prepare_new_snapshot(binding, inputs, storage, docker_client=docker_client,
            seed=seed, uv_binary_digest=uv_binary_digest, image_id=image_id,
            cgroup_parent=cgroup_parent, namespace=namespace, namespace_root=namespace_root.fd)
    finally:
        namespace_root.close()
