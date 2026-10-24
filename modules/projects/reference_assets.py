"""Read the fixed public requirement and independent acceptance assets, without executing them."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import stat

import rfc8785

from modules.workspaces.reference_seed import (
    REFERENCE_COMMIT, REFERENCE_INPUT_DIGEST, REFERENCE_INPUT_SET, REFERENCE_REVISION, _seed_root,
)
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import AcceptanceMetadata, MethodMetadata, RequirementMetadata

REQUIREMENT_PATH = "docs/implementation/reference-requirements-r1.md"
ACCEPTANCE_ROOT = "docs/acceptance/reference/r1/"
ASSET_PATHS = (REQUIREMENT_PATH, *(ACCEPTANCE_ROOT + name for name in ("README.md", "manifest.json", "verify_http.py")))
CHECK_CATALOG_PATH = "docs/acceptance/reference/check-catalog-r1.json"
CHECK_CATALOG_DIGEST = "sha256:85cd4706f3acc9e92b5b774724a125aff6ed66b645537cc4109b1438d6f9abc7"
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ReferenceAssetError(ValueError):
    """Fixed diagnostic only; public file contents never enter error messages."""


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _read_public_file(root: int, path: str) -> bytes:
    """Pin a regular inode under the trusted checkout; DrvFs modes are not private ownership."""
    parent, pinned, reader = os.dup(root), -1, -1
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            following = os.open(part, _DIRECTORY, dir_fd=parent)
            os.close(parent)
            parent = following
        pinned = os.open(parts[-1], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        before = os.fstat(pinned)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 65536:
            raise ReferenceAssetError("reference_asset_file_invalid")
        reader = os.open(f"/proc/self/fd/{pinned}", os.O_RDONLY | os.O_CLOEXEC)
        with os.fdopen(os.dup(reader), "rb") as stream:
            data = stream.read(65537)
        after = os.fstat(reader)
        shape = lambda item: (item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if len(data) != before.st_size or shape(before) != shape(after):
            raise ReferenceAssetError("reference_asset_file_changed")
        return data
    except OSError:
        raise ReferenceAssetError("reference_asset_unavailable") from None
    finally:
        for descriptor in (reader, pinned, parent):
            if descriptor >= 0:
                os.close(descriptor)


def _check_catalog(data: bytes, digests: tuple[tuple[str, str], ...]) -> tuple[dict, tuple[str, ...]]:
    """Consume the independently maintained catalog; never infer requirements from script syntax."""
    if _digest(data) != CHECK_CATALOG_DIGEST:
        raise ReferenceAssetError("reference_check_catalog_digest_mismatch")
    catalog = json.loads(data.decode("utf-8"))
    if (not isinstance(catalog, dict)
            or catalog.get("catalog_revision") != "reference-http-checks-r1"
            or catalog.get("asset_revision") != "reference-public-assets-r2"
            or catalog.get("source_input_set_digest") != REFERENCE_INPUT_DIGEST
            or catalog.get("method_revision") != "reference-http-r1.1"
            or catalog.get("requirement_revision") != "reference-requirements-r1"
            or catalog.get("file_digests") != dict(digests)
            or catalog.get("bundle_digest") != _digest(rfc8785.dumps(dict(digests)))):
        raise ReferenceAssetError("reference_check_catalog_binding_mismatch")
    names = catalog.get("required_check_ids")
    if (not isinstance(names, list) or not 1 <= len(names) <= 64
            or type(catalog.get("check_count")) is not int or catalog["check_count"] != len(names)
            or any(not isinstance(name, str) or not 1 <= len(name) <= 160 for name in names)
            or len(set(names)) != len(names)):
        raise ReferenceAssetError("reference_check_identity_invalid")
    return catalog, tuple(sorted(names))


@dataclass(frozen=True, slots=True)
class ReferenceAssets:
    requirement: RequirementMetadata
    requirement_revision: str
    requirement_digest: str
    method: MethodMetadata
    method_revision: str
    bundle_digest: str
    file_digests: tuple[tuple[str, str], ...]
    required_check_ids: tuple[str, ...]
    frozen_at: datetime

    def acceptance(self, method_ref: EngineeringRef) -> AcceptanceMetadata:
        return AcceptanceMetadata(required_check_ids=self.required_check_ids, method_ref=method_ref)


def load_reference_assets(repository) -> ReferenceAssets:
    """Read the fixed public assets and explicit catalog; reject any unregistered revision."""
    try:
        with _seed_root(repository) as root:
            pinned = _read_public_file(root, REFERENCE_INPUT_SET)
            if _digest(pinned) != REFERENCE_INPUT_DIGEST:
                raise ReferenceAssetError("reference_asset_input_set_mismatch")
            manifest = json.loads(pinned.decode("utf-8"))
            if manifest["revision"] != REFERENCE_REVISION or manifest["source_commit"] != REFERENCE_COMMIT:
                raise ReferenceAssetError("reference_asset_input_set_mismatch")
            contents = {path: _read_public_file(root, path) for path in ASSET_PATHS}
            catalog_data = _read_public_file(root, CHECK_CATALOG_PATH)
        digests = tuple((path, _digest(contents[path])) for path in ASSET_PATHS)
        catalog, checks = _check_catalog(catalog_data, digests)
        independent = json.loads(contents[ACCEPTANCE_ROOT + "manifest.json"].decode("utf-8"))
        if (independent["assets"] != ["README.md", "manifest.json", "verify_http.py"]
                or independent["method_revision"] != "reference-http-r1.1"
                or independent["requirement_revision"] != "reference-requirements-r1"
                or independent["result_binding"]["human_acceptance"] is not None):
            raise ReferenceAssetError("reference_acceptance_manifest_invalid")
        digests += ((CHECK_CATALOG_PATH, CHECK_CATALOG_DIGEST),)
        bundle = _digest(rfc8785.dumps(dict(digests)))
        method = MethodMetadata(description=(
            f"Fixed reference public-asset registration r2; bundle={bundle}; "
            "independent reference-http-r1.1 entry=docs/acceptance/reference/r1/verify_http.py. "
            "HTTP assertions only; restart/fault setup needs operator evidence. "
            "UI interaction, REF-05 migrations and REF-07 topology need separate methods; no result is asserted."
        ))
        return ReferenceAssets(
            requirement=RequirementMetadata(statement=contents[REQUIREMENT_PATH].decode("utf-8")),
            requirement_revision=independent["requirement_revision"], requirement_digest=dict(digests)[REQUIREMENT_PATH],
            method=method, method_revision=independent["method_revision"], bundle_digest=bundle,
            file_digests=digests, required_check_ids=checks,
            frozen_at=datetime.fromisoformat(catalog["frozen_utc"]),
        )
    except ReferenceAssetError:
        raise
    except (ValueError, KeyError, TypeError):
        raise ReferenceAssetError("reference_asset_document_invalid") from None
