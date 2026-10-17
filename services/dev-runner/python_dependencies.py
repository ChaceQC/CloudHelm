"""Fixed reference wheels: bounded public acquisition and read-only seed publication."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import stat
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from modules.workspaces.safe_paths import PrivateRoot, directory_at, read_regular

from .offline_images import SOURCE_DIGEST
from .toolchain import ProbeFailure, private_directory

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "examples/standalone-project/backend"
CACHE_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/python-dependency-seeds")
UV_FILENAME = "uv-0.11.29-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
UV_WHEEL = {"filename": UV_FILENAME, "name": "uv", "version": "0.11.29",
    "url": "https://files.pythonhosted.org/packages/0d/28/3fa1c2061d588184840e3e4ab17e6d318c744bb2fcb15ddb0c29b5bc0bb3/" + UV_FILENAME,
    "hash": "sha256:eec03a8b63d55915694db3af4e91324b39ced49e2aeac7af37851c7eb3f470ea", "size": 26914059}
INPUT_DIGESTS = {
    "pyproject.toml": "sha256:b5940017da0d4aa230ccd04353eff3c05e47175f349c46106fa1a74287907148",
    "uv.lock": "sha256:ee1eaa6cb0a358d724f8a553265cf59b411248ece569d9bca05f44ae649e7bd2",
    ".python-version": "sha256:aa0d6581054e6e4ff3f91839deca7a854ad37221b8784d060b42d0f847ff1a3b",
}
SYNC_ARGUMENTS = ("sync", "--locked", "--no-dev", "--offline", "--no-build",
    "--no-install-project", "--no-index", "--find-links=/wheelhouse", "--link-mode=copy",
    "--python=/usr/local/bin/python", "--no-python-downloads")
LOCK_ARGUMENTS = ("lock", "--offline", "--no-build", "--no-index", "--find-links=/wheelhouse",
                  "--python=/usr/local/bin/python", "--no-python-downloads")
DERIVED_ENVIRONMENT = "sys_platform == 'linux' and platform_machine == 'x86_64' and implementation_name == 'cpython'"
MAX_DOWNLOAD_BYTES, MAX_SEED_BYTES = 64 * 1024**2, 256 * 1024**2
ACQUISITION_SECONDS = 240


def _encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PythonDependencyInput:
    project: str = "cloudhelm-reference-notes"
    trust_domain: str = "p0-controlled-reference"
    platform: str = "linux/amd64"
    python: str = "3.12.13"
    uv: str = "0.11.29"
    base_index_digest: str = SOURCE_DIGEST
    uv_wheel_digest: str = UV_WHEEL["hash"]
    project_digest: str = INPUT_DIGESTS["pyproject.toml"]
    lock_digest: str = INPUT_DIGESTS["uv.lock"]
    python_pin_digest: str = INPUT_DIGESTS[".python-version"]
    install_arguments: tuple[str, ...] = SYNC_ARGUMENTS

    @property
    def cache_key(self) -> str:
        return hashlib.sha256(_encoded(asdict(self))).hexdigest()

    def require_supported(self) -> None:
        if self != PythonDependencyInput():
            raise ProbeFailure("python_dependency_input_not_supported")


def reference_inputs(source_files: Mapping[str, bytes] | None = None) -> dict[str, bytes]:
    result = {}
    for name, digest in INPUT_DIGESTS.items():
        if source_files is None:
            path = REFERENCE / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024**2:
                raise ProbeFailure("python_dependency_reference_file_invalid")
            result[name] = path.read_bytes()
        else:
            result[name] = source_files.get(name)
        if type(result[name]) is not bytes or _digest(result[name]) != digest:
            raise ProbeFailure("python_dependency_reference_digest_changed")
    project = tomllib.loads(result["pyproject.toml"].decode("utf-8"))
    if (result[".python-version"].decode("utf-8").strip() != "3.12.13"
            or project.get("tool", {}).get("uv") != {"package": False}
            or project["project"]["requires-python"] != "==3.12.*"):
        raise ProbeFailure("python_dependency_reference_configuration_unsupported")
    return result


def _compatible(filename: str) -> bool:
    if not filename.endswith(".whl"):
        return False
    parts = filename[:-4].rsplit("-", 3)
    if len(parts) != 4:
        return False
    _, python, abi, platforms = parts
    if abi == "none" and "py3" in python.split(".") and platforms == "any":
        return True
    if python != "cp312" or abi not in ("cp312", "abi3"):
        return False
    for platform in platforms.split("."):
        match = re.fullmatch(r"manylinux_2_([0-9]+)_x86_64", platform)
        if platform in {"manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64"}:
            return True
        if match and 5 <= int(match[1]) <= 36:
            return True
    return False


def _selected_packages(lock: dict) -> list[dict]:
    packages = {item["name"]: item for item in lock["package"]}
    if len(packages) != len(lock["package"]) or lock.get("requires-python") != "==3.12.*":
        raise ProbeFailure("python_dependency_lock_shape_unsupported")
    pending, visited, names = [("cloudhelm-reference-notes-backend", ())], set(), set()
    markers = {"sys_platform == 'win32'": False, "implementation_name != 'pypy'": True}
    while pending:
        name, extras = pending.pop()
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        package = packages[name]
        if package.get("source") != {"virtual": "."}:
            if package.get("source") != {"registry": "https://pypi.org/simple"}:
                raise ProbeFailure("python_dependency_source_unsupported")
            names.add(name)
        dependencies = list(package.get("dependencies", []))
        for extra in extras:
            dependencies += package.get("optional-dependencies", {})[extra]
        for item in dependencies:
            marker = item.get("marker")
            if marker is not None and marker not in markers:
                raise ProbeFailure("python_dependency_marker_unsupported")
            if marker is None or markers[marker]:
                pending.append((item["name"], tuple(item.get("extra", []))))
    return [packages[name] for name in sorted(names)]


def wheel_plan(source_files: Mapping[str, bytes] | None = None) -> list[dict]:
    lock = tomllib.loads(reference_inputs(source_files)["uv.lock"].decode("utf-8"))
    result = []
    for package in _selected_packages(lock):
        wheels = []
        for wheel in package.get("wheels", []):
            filename = urllib.parse.urlsplit(wheel["url"]).path.rsplit("/", 1)[-1]
            if _compatible(filename):
                wheels.append(wheel | {"filename": filename})
        if not wheels:
            raise ProbeFailure("python_dependency_compatible_wheel_required_no_sdist")
        wheel = sorted(wheels, key=lambda item: ("-py" in item["filename"], item["filename"]))[0]
        result.append({key: wheel[key] for key in ("filename", "url", "hash", "size")}
                      | {"name": package["name"], "version": package["version"]})
    if len(result) > 32 or sum(item["size"] for item in result + [UV_WHEEL]) > MAX_SEED_BYTES:
        raise ProbeFailure("python_dependency_download_set_exceeded")
    return result


def derived_project(source_files: Mapping[str, bytes] | None = None) -> bytes:
    return reference_inputs(source_files)["pyproject.toml"] + ("\nenvironments = [" + json.dumps(DERIVED_ENVIRONMENT) + "]\n").encode("utf-8")


def verify_derived_inputs(project: bytes, lock: bytes, distributions: dict,
                          source_files: Mapping[str, bytes] | None = None) -> dict:
    if project != derived_project(source_files) or len(lock) > 1024**2:
        raise ProbeFailure("python_dependency_derived_project_mismatch")
    value = tomllib.loads(lock.decode("utf-8"))
    packages = value.get("package", [])
    external = [item for item in packages if item.get("source") != {"virtual": "."}]
    actual = {item["name"]: item["version"] for item in external}
    if actual != distributions or len(actual) != len(external):
        raise ProbeFailure("python_dependency_derived_lock_distribution_drift")
    expected = {item["name"]: item for item in wheel_plan(source_files)}
    for item in external:
        wheels = item.get("wheels", [])
        if (item.get("source") != {"registry": "/wheelhouse"} or item.get("sdist") or len(wheels) != 1
                or wheels[0].get("hash", expected[item["name"]]["hash"]) != expected[item["name"]]["hash"]
                or Path(wheels[0].get("path", "")).name != expected[item["name"]]["filename"]):
            raise ProbeFailure("python_dependency_derived_lock_wheel_mismatch")
    return {"variant": "linux-amd64-wheelhouse-r1", "environment": DERIVED_ENVIRONMENT,
        "source_lock_digest": INPUT_DIGESTS["uv.lock"], "project_digest": _digest(project),
        "lock_digest": _digest(lock), "lock_arguments": LOCK_ARGUMENTS,
        "original_linux_name_versions_match": True, "derived_wheels_reference_verified_seed": True}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise ProbeFailure("python_dependency_redirect_rejected")


def _download(item: dict, destination: Path, started: float) -> None:
    endpoint = urllib.parse.urlsplit(item["url"])
    if (endpoint.scheme != "https" or endpoint.netloc != "files.pythonhosted.org"
            or endpoint.query or endpoint.fragment
            or not re.fullmatch(r"/packages/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{60}/[A-Za-z0-9_.+-]+\.whl", endpoint.path)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["hash"])
            or not 0 < item["size"] <= MAX_DOWNLOAD_BYTES):
        raise ProbeFailure("python_dependency_download_descriptor_rejected")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(item["url"], headers={"Accept-Encoding": "identity"})
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    size, digest = 0, hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as output, opener.open(request, timeout=20) as response:
            if response.status != 200 or int(response.headers.get("Content-Length", "-1")) != item["size"]:
                raise ProbeFailure("python_dependency_download_response_rejected")
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > item["size"] or time.monotonic() - started > ACQUISITION_SECONDS:
                    raise ProbeFailure("python_dependency_download_bound_exceeded")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, urllib.error.URLError, ValueError):
        raise ProbeFailure("python_dependency_fixed_https_download_failed") from None
    if size != item["size"] or "sha256:" + digest.hexdigest() != item["hash"]:
        raise ProbeFailure("python_dependency_download_digest_mismatch")
    destination.chmod(0o400)


def _uv_binary(path: Path) -> bytes:
    with zipfile.ZipFile(path) as wheel:
        entries = [item for item in wheel.infolist() if item.filename.endswith(".data/scripts/uv")]
        if len(entries) != 1 or not 0 < entries[0].file_size <= 128 * 1024**2:
            raise ProbeFailure("python_dependency_uv_wheel_entry_unsupported")
        return wheel.read(entries[0])


def _new_file(path: Path, content: bytes, mode: int = 0o400) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _manifest(inputs: PythonDependencyInput, wheels: list[dict], binary: bytes) -> dict:
    return {"schema": "p1-python-dependency-seed-r1", "cache_key": inputs.cache_key,
        "input_identity": json.loads(_encoded(asdict(inputs))), "wheels": wheels,
        "uv_wheel": UV_WHEEL, "uv_binary": {"hash": _digest(binary), "size": len(binary)}}


def _checked_file(path: Path, digest: str, size: int) -> None:
    state = path.lstat()
    if (not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid()
            or state.st_mode & 0o222 or state.st_size != size):
        raise ProbeFailure("python_dependency_seed_file_boundary_invalid")
    with path.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise ProbeFailure("python_dependency_seed_content_mismatch")


def verify_seed(path: Path, inputs: PythonDependencyInput, *,
                source_files: Mapping[str, bytes] | None = None) -> dict:
    inputs.require_supported()
    if path != CACHE_ROOT / inputs.cache_key:
        raise ProbeFailure("python_dependency_seed_key_mismatch")
    wheels = wheel_plan(source_files)
    expected_files = {"manifest.json", "uv", "uv.whl"} | {"wheels/" + item["filename"] for item in wheels}
    actual_files = set()
    for entry in [path, *path.rglob("*")]:
        state = entry.lstat()
        if state.st_uid != os.getuid() or state.st_mode & 0o222 or stat.S_ISLNK(state.st_mode):
            raise ProbeFailure("python_dependency_seed_not_readonly")
        if stat.S_ISREG(state.st_mode):
            actual_files.add(str(entry.relative_to(path)))
        elif not stat.S_ISDIR(state.st_mode) or entry not in (path, path / "wheels"):
            raise ProbeFailure("python_dependency_seed_member_unsupported")
    if actual_files != expected_files:
        raise ProbeFailure("python_dependency_seed_members_mismatch")
    for item in wheels:
        _checked_file(path / "wheels" / item["filename"], item["hash"], item["size"])
    _checked_file(path / "uv.whl", UV_WHEEL["hash"], UV_WHEEL["size"])
    binary = _uv_binary(path / "uv.whl")
    _checked_file(path / "uv", _digest(binary), len(binary))
    manifest = _encoded(_manifest(inputs, wheels, binary))
    _checked_file(path / "manifest.json", _digest(manifest), len(manifest))
    retained = sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
    if retained > MAX_SEED_BYTES:
        raise ProbeFailure("python_dependency_seed_retention_bound_exceeded")
    return {"cache_key": inputs.cache_key, "path": str(path), "manifest_digest": _digest(manifest),
        "wheel_count": len(wheels), "retained_bytes": retained,
        "distributions": {item["name"]: item["version"] for item in wheels}}


def verify_admitted_seed(path: Path, inputs: PythonDependencyInput, *,
                         source_files: Mapping[str, bytes] | None = None) -> dict:
    """Verify a byte-identical seed copied by the caller holding storage admission."""
    from .development_storage import ROOT as STORAGE_ROOT, mounted_identity, validate_id

    inputs.require_supported()
    try:
        parts = path.relative_to(STORAGE_ROOT).parts
    except ValueError:
        raise ProbeFailure("python_dependency_admitted_seed_path_invalid") from None
    if (len(parts) != 5 or parts[1:4] != ("data", "cache", "python")
            or parts[4] != inputs.cache_key or ".." in path.parts):
        raise ProbeFailure("python_dependency_admitted_seed_path_invalid")
    validate_id(parts[0])
    data, root = PrivateRoot(path.parents[2]), None
    try:
        mounted_identity(data.fd, parts[0])
        root = PrivateRoot(path)
        if os.fstat(root.fd).st_dev != os.fstat(data.fd).st_dev:
            raise ProbeFailure("python_dependency_admitted_seed_device_mismatch")
        wheels = wheel_plan(source_files)
        if (os.fstat(root.fd).st_mode & 0o222
                or set(os.listdir(root.fd)) != {"manifest.json", "uv", "uv.whl", "wheels"}):
            raise ProbeFailure("python_dependency_seed_members_mismatch")
        retained = 0

        def checked(parent, name, expected_digest, expected_size):
            nonlocal retained
            state = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISREG(state.st_mode) or state.st_mode & 0o222
                    or state.st_size != expected_size):
                raise ProbeFailure("python_dependency_seed_file_boundary_invalid")
            raw = read_regular(parent, name, expected_size)
            if _digest(raw) != expected_digest:
                raise ProbeFailure("python_dependency_seed_content_mismatch")
            retained += len(raw)
            return raw

        with directory_at(root.fd, "wheels") as wheel_directory:
            if (os.fstat(wheel_directory).st_mode & 0o222
                    or set(os.listdir(wheel_directory)) != {item["filename"] for item in wheels}):
                raise ProbeFailure("python_dependency_seed_members_mismatch")
            for item in wheels:
                checked(wheel_directory, item["filename"], item["hash"], item["size"])
        uv_wheel = checked(root.fd, "uv.whl", UV_WHEEL["hash"], UV_WHEEL["size"])
        binary = _uv_binary(io.BytesIO(uv_wheel))
        checked(root.fd, "uv", _digest(binary), len(binary))
        manifest = _encoded(_manifest(inputs, wheels, binary))
        checked(root.fd, "manifest.json", _digest(manifest), len(manifest))
        if retained > MAX_SEED_BYTES:
            raise ProbeFailure("python_dependency_seed_retention_bound_exceeded")
        return {"cache_key": inputs.cache_key, "path": str(path), "manifest_digest": _digest(manifest),
            "wheel_count": len(wheels), "retained_bytes": retained,
            "distributions": {item["name"]: item["version"] for item in wheels}}
    finally:
        if root is not None:
            root.close()
        data.close()


def prepare_seed(inputs: PythonDependencyInput, *, source_files: Mapping[str, bytes] | None = None) -> dict:
    inputs.require_supported()
    private_directory(CACHE_ROOT)
    lock = os.open(CACHE_ROOT / "prepare.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stage = None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = CACHE_ROOT / inputs.cache_key
        if target.exists():
            return verify_seed(target, inputs, source_files=source_files) | {"cache_hit": True, "downloaded_bytes": 0}
        stage = CACHE_ROOT / ("prepare-" + uuid4().hex)
        stage.mkdir(mode=0o700)
        (stage / "wheels").mkdir(mode=0o700)
        wheels, started = wheel_plan(source_files), time.monotonic()
        for item in wheels:
            _download(item, stage / "wheels" / item["filename"], started)
        _download(UV_WHEEL, stage / "uv.whl", started)
        binary = _uv_binary(stage / "uv.whl")
        _new_file(stage / "uv", binary, 0o500)
        _new_file(stage / "manifest.json", _encoded(_manifest(inputs, wheels, binary)))
        (stage / "wheels").chmod(0o500)
        stage.chmod(0o500)
        os.rename(stage, target)
        stage = None
        return verify_seed(target, inputs, source_files=source_files) | {"cache_hit": False,
            "downloaded_bytes": sum(item["size"] for item in wheels + [UV_WHEEL])}
    except BlockingIOError:
        raise ProbeFailure("python_dependency_seed_preparation_busy") from None
    finally:
        if stage is not None and stage.exists():
            stage.chmod(0o700)
            (stage / "wheels").chmod(0o700)
            shutil.rmtree(stage)
        os.close(lock)
