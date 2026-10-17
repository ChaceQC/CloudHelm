"""Read the fixed public requirement and independent acceptance assets, without executing them."""

import ast
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


def _required_checks(script: bytes) -> tuple[str, ...]:
    """Read the pinned r1 checker names statically, including its two title-boundary cases."""
    names = []
    for node in ast.walk(ast.parse(script.decode("utf-8"))):
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                or not isinstance(node.func.value, ast.Name) or node.func.value.id != "result"
                or node.func.attr != "run" or not node.args):
            continue
        name = node.args[0]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            names.append(name.value)
        elif isinstance(name, ast.JoinedStr):
            pattern = "".join(part.value if isinstance(part, ast.Constant) else "{size}" for part in name.values)
            if pattern not in {"REF-03.title_{size}_accepted", "REF-03.title_{size}_accepted_length"}:
                raise ReferenceAssetError("reference_check_identity_unsupported")
            names.extend(pattern.format(size=size) for size in (1, 120))
        else:
            raise ReferenceAssetError("reference_check_identity_unsupported")
    if not 1 <= len(names) <= 64 or len(set(names)) != len(names):
        raise ReferenceAssetError("reference_check_identity_invalid")
    return tuple(sorted(names))


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
    """Only the r1 public allowlist is read; a changed manifest or asset is rejected."""
    try:
        with _seed_root(repository) as root:
            pinned = _read_public_file(root, REFERENCE_INPUT_SET)
            if _digest(pinned) != REFERENCE_INPUT_DIGEST:
                raise ReferenceAssetError("reference_asset_input_set_mismatch")
            manifest = json.loads(pinned.decode("utf-8"))
            if manifest["revision"] != REFERENCE_REVISION or manifest["source_commit"] != REFERENCE_COMMIT:
                raise ReferenceAssetError("reference_asset_input_set_mismatch")
            expected = {item["path"]: "sha256:" + item["sha256"] for item in manifest["files"]}
            contents = {path: _read_public_file(root, path) for path in ASSET_PATHS}
        digests = tuple((path, _digest(contents[path])) for path in ASSET_PATHS)
        if any(digest != expected[path] for path, digest in digests):
            raise ReferenceAssetError("reference_asset_digest_mismatch")
        independent = json.loads(contents[ACCEPTANCE_ROOT + "manifest.json"].decode("utf-8"))
        if (independent["assets"] != ["README.md", "manifest.json", "verify_http.py"]
                or independent["method_revision"] != "reference-http-r1.1"
                or independent["requirement_revision"] != "reference-requirements-r1"
                or independent["result_binding"]["human_acceptance"] is not None):
            raise ReferenceAssetError("reference_acceptance_manifest_invalid")
        bundle = _digest(rfc8785.dumps(dict(digests)))
        method = MethodMetadata(description=(
            f"Fixed reference r1 public-asset registration; bundle={bundle}; "
            "independent reference-http-r1.1 entry=docs/acceptance/reference/r1/verify_http.py. "
            "HTTP assertions only; restart/fault setup needs operator evidence. "
            "UI interaction, REF-05 migrations and REF-07 topology need separate methods; no result is asserted."
        ))
        return ReferenceAssets(
            requirement=RequirementMetadata(statement=contents[REQUIREMENT_PATH].decode("utf-8")),
            requirement_revision=independent["requirement_revision"], requirement_digest=dict(digests)[REQUIREMENT_PATH],
            method=method, method_revision=independent["method_revision"], bundle_digest=bundle,
            file_digests=digests, required_check_ids=_required_checks(contents[ACCEPTANCE_ROOT + "verify_http.py"]),
            frozen_at=datetime.fromisoformat(manifest["frozen_utc"]),
        )
    except ReferenceAssetError:
        raise
    except (ValueError, KeyError, TypeError):
        raise ReferenceAssetError("reference_asset_document_invalid") from None
