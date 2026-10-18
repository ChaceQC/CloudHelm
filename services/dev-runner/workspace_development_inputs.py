"""Fixed dependency inputs for the mutable P1.2 Workspace runtime."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from typing import Mapping

import rfc8785

from modules.workspaces.safe_paths import PrivateRoot, read_regular
from packages.contracts.p1.workspace_git import WorkspaceBinding, content_digest

from . import python_dependencies
from .offline_images import SOURCE_DIGEST, SOURCE_REFERENCE
from .toolchain import ProbeFailure

METHOD = "p1-workspace-python-dependencies-r1"
PLATFORM = "linux/amd64"
PYTHON_VERSION = "3.12.13"
UV_VERSION = "0.11.29"
MAX_CONTROL_FILE_BYTES = 128 * 1024
BACKEND_ROOT = "backend"
LOCK_COMMENT_VARIANT = b"# CloudHelm fixed dependency lock comment variant: p1-workspace-python-r1\n"
WORKSPACE_INSTALL_ENVIRONMENT = tuple(sorted({
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "UV_CACHE_DIR": "/private-cache",
    "UV_PROJECT_ENVIRONMENT": "/environment",
    "UV_PYTHON_DOWNLOADS": "never",
    "UV_KEYRING_PROVIDER": "disabled",
    "PYTHONDONTWRITEBYTECODE": "1",
}.items()))
WORKSPACE_INSTALL_WORKDIR = "/snapshot"


@dataclass(frozen=True)
class WorkspacePythonToolchain:
    """The only Python toolchain this slice can prepare."""

    platform: str = PLATFORM
    python: str = PYTHON_VERSION
    uv: str = UV_VERSION
    python_image_reference: str = SOURCE_REFERENCE
    python_image_digest: str = SOURCE_DIGEST
    uv_wheel_digest: str = python_dependencies.UV_WHEEL["hash"]

    @property
    def digest(self) -> str:
        payload = json.dumps(self.identity(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def identity(self) -> dict[str, str]:
        return {"platform": self.platform, "python": self.python, "uv": self.uv,
                "python_image_reference": self.python_image_reference,
                "python_image_digest": self.python_image_digest, "uv_wheel_digest": self.uv_wheel_digest}

    def require_supported(self) -> None:
        if self != WorkspacePythonToolchain():
            raise ProbeFailure("workspace_python_toolchain_unsupported")


WORKSPACE_PYTHON_TOOLCHAIN = WorkspacePythonToolchain()


@dataclass(frozen=True)
class WorkspaceDependencyInputs:
    """Byte-verified input snapshot; Workspace revisions do not poison lock reuse."""

    project_id: str
    workspace_id: str
    workspace_key: str
    project_name: str
    project_version: str
    pyproject_bytes: bytes = field(repr=False)
    lock_bytes: bytes = field(repr=False)
    python_pin_bytes: bytes = field(repr=False)
    project_digest: str
    lock_digest: str
    python_pin_digest: str
    dependency_cache_key: str
    seed_manifest_digest: str
    seed_path: str
    toolchain: WorkspacePythonToolchain
    distributions: tuple[tuple[str, str], ...]
    install_arguments: tuple[str, ...]
    install_environment: tuple[tuple[str, str], ...]
    install_workdir: str
    environment_key: str

    def identity(self) -> dict:
        return {"schema_revision": "p1-workspace-python-dependencies-r1",
            "project_id": self.project_id, "workspace_id": self.workspace_id,
            "workspace_key": self.workspace_key, "trust_domain": "p0-controlled-reference",
            "dependency_project": "cloudhelm-reference-notes", "project_name": self.project_name,
            "project_version": self.project_version, "project_digest": self.project_digest,
            "lock_digest": self.lock_digest, "python_pin_digest": self.python_pin_digest,
            "dependency_cache_key": self.dependency_cache_key,
            "seed_manifest_digest": self.seed_manifest_digest,
            "toolchain": self.toolchain.identity(), "toolchain_digest": self.toolchain.digest,
            "platform": self.toolchain.platform, "install_arguments": list(self.install_arguments),
            "install_environment": dict(self.install_environment), "install_workdir": self.install_workdir,
            "distributions": dict(self.distributions)}


def workspace_storage_id(binding: WorkspaceBinding) -> str:
    """Match WorkfileStore's stable physical namespace for one project/workspace pair."""
    if type(binding) is not WorkspaceBinding:
        raise ProbeFailure("workspace_python_binding_invalid")
    canonical = rfc8785.dumps([binding.project_id, binding.workspace_id])
    return "workspace-" + hashlib.sha256(canonical).hexdigest()


def read_workspace_backend_inputs(storage, binding: WorkspaceBinding) -> dict[str, bytes]:
    """Capture only dependency control files under the common Workspace write lock."""
    if type(binding) is not WorkspaceBinding:
        raise ProbeFailure("workspace_python_binding_invalid")
    try:
        storage.observe()
        root = PrivateRoot(storage.workspace_root)
        try:
            with root.exclusive() as directory:
                workspace_id = workspace_storage_id(binding)
                prefix = workspace_id + "/files/" + BACKEND_ROOT + "/"
                return {name: read_regular(directory, prefix + name, MAX_CONTROL_FILE_BYTES)
                    for name in ("pyproject.toml", "uv.lock", ".python-version")}
        finally:
            root.close()
    except ProbeFailure:
        raise
    except (OSError, ValueError, AttributeError):
        raise ProbeFailure("workspace_python_source_snapshot_unavailable") from None


def validate_workspace_dependency_inputs(binding: WorkspaceBinding, source_files: Mapping[str, bytes], *,
        dependency_input: python_dependencies.PythonDependencyInput,
        seed_receipt: Mapping[str, object], toolchain: WorkspacePythonToolchain = WORKSPACE_PYTHON_TOOLCHAIN
        ) -> WorkspaceDependencyInputs:
    """Reject every project/lock shape outside the original lock or one fixed comment variant."""
    if type(binding) is not WorkspaceBinding or not isinstance(source_files, Mapping):
        raise ProbeFailure("workspace_python_inputs_invalid")
    dependency_input.require_supported()
    toolchain.require_supported()
    if set(source_files) != {"pyproject.toml", "uv.lock", ".python-version"} or any(
            type(raw) is not bytes or len(raw) > MAX_CONTROL_FILE_BYTES for raw in source_files.values()):
        raise ProbeFailure("workspace_python_source_members_or_bounds_mismatch")

    expected = python_dependencies.reference_inputs()
    pyproject_bytes, lock_bytes, python_pin_bytes = (
        source_files["pyproject.toml"], source_files["uv.lock"], source_files[".python-version"])
    if pyproject_bytes != expected["pyproject.toml"] or python_pin_bytes != expected[".python-version"]:
        raise ProbeFailure("workspace_python_project_or_pin_unsupported")
    if lock_bytes not in (expected["uv.lock"], expected["uv.lock"] + LOCK_COMMENT_VARIANT):
        raise ProbeFailure("workspace_python_lock_unsupported")

    try:
        project = tomllib.loads(pyproject_bytes.decode("utf-8"))
        lock = tomllib.loads(lock_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProbeFailure("workspace_python_lock_parse_failed") from None
    project_fields = project.get("project")
    if (not isinstance(project_fields, dict) or project_fields.get("name") != "cloudhelm-reference-notes-backend"
            or project_fields.get("version") != "0.0.0"):
        raise ProbeFailure("workspace_python_project_identity_mismatch")
    roots = [item for item in lock.get("package", []) if item.get("source") == {"virtual": "."}]
    if (len(roots) != 1 or roots[0].get("name") != project_fields["name"]
            or roots[0].get("version") != project_fields["version"]):
        raise ProbeFailure("workspace_python_lock_project_identity_mismatch")

    packages = python_dependencies._selected_packages(lock)
    distributions = tuple(sorted((item["name"], item["version"]) for item in packages))
    expected_distributions = seed_receipt.get("distributions")
    if (not isinstance(expected_distributions, dict)
            or dict(distributions) != expected_distributions
            or seed_receipt.get("cache_key") != dependency_input.cache_key
            or not isinstance(seed_receipt.get("manifest_digest"), str)
            or not seed_receipt["manifest_digest"].startswith("sha256:")):
        raise ProbeFailure("workspace_python_seed_lock_distribution_mismatch")

    project_digest = content_digest(pyproject_bytes)
    lock_digest = content_digest(lock_bytes)
    python_pin_digest = content_digest(python_pin_bytes)
    workspace_key = hashlib.sha256(rfc8785.dumps([binding.project_id, binding.workspace_id])).hexdigest()
    install_arguments = tuple(dependency_input.install_arguments) + ("--no-cache",)
    install_environment = WORKSPACE_INSTALL_ENVIRONMENT
    install_workdir = WORKSPACE_INSTALL_WORKDIR
    identity = {"schema_revision": "p1-workspace-python-dependencies-r1",
        "project_id": binding.project_id, "workspace_id": binding.workspace_id,
        "workspace_key": workspace_key, "trust_domain": dependency_input.trust_domain,
        "dependency_project": dependency_input.project,
        "project_name": project_fields["name"], "project_version": project_fields["version"],
        "project_digest": project_digest, "lock_digest": lock_digest,
        "python_pin_digest": python_pin_digest, "dependency_cache_key": dependency_input.cache_key,
        "seed_manifest_digest": seed_receipt["manifest_digest"], "toolchain": toolchain.identity(),
        "toolchain_digest": toolchain.digest, "platform": toolchain.platform,
        "install_arguments": list(install_arguments), "install_environment": dict(install_environment),
        "install_workdir": install_workdir, "distributions": dict(distributions)}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return WorkspaceDependencyInputs(
        project_id=binding.project_id, workspace_id=binding.workspace_id, workspace_key=workspace_key,
        project_name=project_fields["name"], project_version=project_fields["version"],
        pyproject_bytes=pyproject_bytes, lock_bytes=lock_bytes, python_pin_bytes=python_pin_bytes,
        project_digest=project_digest, lock_digest=lock_digest, python_pin_digest=python_pin_digest,
        dependency_cache_key=dependency_input.cache_key,
        seed_manifest_digest=seed_receipt["manifest_digest"], seed_path=str(seed_receipt["path"]),
        toolchain=toolchain, distributions=distributions, install_arguments=install_arguments,
        install_environment=install_environment, install_workdir=install_workdir,
        environment_key=key)
