"""Fixed frontend download identity; raw tarballs are not an npm cacache."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Annotated, Literal

import rfc8785
from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest
from packages.contracts.p0.engineering_contracts import UtcTimestamp

PACKAGE_DIGEST = "sha256:a31617b5724f31eb9089b347389504bbec7e60cbceab543615283a79cca68858"
LOCK_DIGEST = "sha256:21b2a52e6e77526a24821f558a7a34b7b02766a0917c5a95d980f879c88e4ad4"
INPUT_BYTES = 61821
TARBALL_COUNT = 119
MAX_TARBALL_BYTES = 32 * 1024 * 1024
MAX_TARBALL_TOTAL = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
REGISTRY = "https://registry.npmjs.org"
NODE_IMAGE = "node:22.23.2-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9"
NPM_VERSION = "10.9.8"  # Bundled package verified from the pinned Node OCI layers.
INSTALL_OPTIONS = ("--offline", "--ignore-scripts", "--include=dev", "--include=optional",
                   "--no-audit", "--no-fund")
SeedId = Annotated[str, Field(pattern=r"^npm-seed-[0-9a-f]{64}$")]
Namespace = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")]
PACKAGE_NAME = r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+"
VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?"


class NpmDownloadSpec(Contract):
    schema_revision: Literal["p1-npm-download-key-r1"] = "p1-npm-download-key-r1"
    project_id: Namespace
    trust_domain: Namespace
    node_version: Literal["22.23.2"] = "22.23.2"
    node_image: Literal[NODE_IMAGE] = NODE_IMAGE
    package_manager: Literal["npm-bundled-with-node"] = "npm-bundled-with-node"
    platform: Literal["linux/amd64"] = "linux/amd64"
    registry: Literal["https://registry.npmjs.org"] = REGISTRY
    package_digest: Literal[PACKAGE_DIGEST] = PACKAGE_DIGEST
    lock_digest: Literal[LOCK_DIGEST] = LOCK_DIGEST
    lockfile_version: Literal[3] = 3
    install_command: Literal["npm ci"] = "npm ci"
    install_options: tuple[str, ...] = INSTALL_OPTIONS

    @model_validator(mode="after")
    def check_install_options(self):
        if self.install_options != INSTALL_OPTIONS:
            raise ValueError("npm_install_options_unsupported")
        return self


def canonical(value: Contract) -> bytes:
    return rfc8785.dumps(value.model_dump(mode="json"))


def npm_seed_id(spec: NpmDownloadSpec) -> str:
    return "npm-seed-" + hashlib.sha256(canonical(spec)).hexdigest()


class LockedNpmTarball(Contract):
    package_path: str = Field(pattern=r"^node_modules/" + PACKAGE_NAME + r"$")
    version: str = Field(pattern=r"^" + VERSION + r"$")
    url: str = Field(max_length=512)
    integrity: str = Field(pattern=r"^sha512-[A-Za-z0-9+/]{86}==$", max_length=95)

    @model_validator(mode="after")
    def check_registry_integrity(self):
        name = self.package_path.removeprefix("node_modules/")
        expected = f"{REGISTRY}/{name}/-/{name.rsplit('/', 1)[-1]}-{self.version}.tgz"
        if self.url != expected:
            raise ValueError("npm_registry_url_unsupported")
        raw = base64.b64decode(self.integrity[7:], validate=True)
        if len(raw) != 64 or base64.b64encode(raw).decode("ascii") != self.integrity[7:]:
            raise ValueError("npm_integrity_unsupported")
        return self

    @property
    def content_digest(self) -> str:
        return "sha512:" + base64.b64decode(self.integrity[7:], validate=True).hex()

    @property
    def blob_name(self) -> str:
        return "sha512-" + self.content_digest[7:] + ".tgz"


class NpmSeedTarball(LockedNpmTarball):
    filename: str = Field(pattern=r"^sha512-[0-9a-f]{128}\.tgz$")
    sha512: str = Field(pattern=r"^sha512:[0-9a-f]{128}$")
    sha256: Digest
    bytes: int = Field(strict=True, gt=0, le=MAX_TARBALL_BYTES)

    @model_validator(mode="after")
    def check_blob_identity(self):
        expected = "sha512:" + base64.b64decode(self.integrity[7:], validate=True).hex()
        if self.sha512 != expected or self.filename != "sha512-" + expected[7:] + ".tgz":
            raise ValueError("npm_tarball_identity_mismatch")
        return self


class NpmSeedManifest(Contract):
    schema_revision: Literal["p1-npm-download-seed-r1"] = "p1-npm-download-seed-r1"
    cache_id: SeedId
    spec: NpmDownloadSpec
    created_at: UtcTimestamp
    format: Literal["raw-npm-tarballs"] = "raw-npm-tarballs"
    npm_cacache: Literal[False] = False
    lifecycle_scripts_executed: Literal[False] = False
    input_bytes: Literal[INPUT_BYTES] = INPUT_BYTES
    file_count: Literal[122] = 122
    tarballs: tuple[NpmSeedTarball, ...] = Field(min_length=TARBALL_COUNT, max_length=TARBALL_COUNT)
    tarball_bytes: int = Field(strict=True, gt=0, le=MAX_TARBALL_TOTAL)

    @model_validator(mode="after")
    def check_seed_identity(self):
        paths = [item.package_path for item in self.tarballs]
        if self.cache_id != npm_seed_id(self.spec):
            raise ValueError("npm_cache_key_mismatch")
        if paths != sorted(set(paths)) or len({item.filename for item in self.tarballs}) != len(paths):
            raise ValueError("npm_seed_tarballs_not_unique_sorted")
        if sum(item.bytes for item in self.tarballs) != self.tarball_bytes:
            raise ValueError("npm_seed_byte_count_mismatch")
        return self


class NpmSeedReceipt(Contract):
    manifest: NpmSeedManifest
    manifest_digest: Digest
    manifest_bytes: int = Field(strict=True, gt=0, le=MAX_MANIFEST_BYTES)
    seed_bytes: int = Field(strict=True, gt=0, le=MAX_TARBALL_TOTAL + INPUT_BYTES + MAX_MANIFEST_BYTES)
    cache_hit: bool = Field(strict=True)
    host_physical_quota: Literal[False] = False

    @model_validator(mode="after")
    def check_receipt(self):
        raw = canonical(self.manifest)
        if (self.manifest_digest != "sha256:" + hashlib.sha256(raw).hexdigest()
                or self.manifest_bytes != len(raw)
                or self.seed_bytes != self.manifest.tarball_bytes + INPUT_BYTES + len(raw)):
            raise ValueError("npm_seed_receipt_mismatch")
        return self


def strict_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("npm_json_duplicate_key")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("npm_json_object_required")
    return value


def _metadata(value: dict) -> None:
    allowed = {"version", "resolved", "integrity", "dev", "optional", "license", "engines",
               "dependencies", "optionalDependencies", "peerDependencies", "peerDependenciesMeta",
               "funding", "bin", "os", "cpu", "hasInstallScript"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("npm_lock_fields_unsupported")
    for field in ("dev", "optional", "hasInstallScript"):
        if field in value and type(value[field]) is not bool:
            raise ValueError("npm_lock_flag_unsupported")
    for field in ("dependencies", "optionalDependencies", "peerDependencies", "engines", "bin"):
        if field in value and (not isinstance(value[field], dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value[field].items())):
            raise ValueError("npm_lock_map_unsupported")
    for field in ("dependencies", "optionalDependencies", "peerDependencies"):
        for name, selector in value.get(field, {}).items():
            if not re.fullmatch(PACKAGE_NAME, name) or not re.fullmatch(r"[A-Za-z0-9.*^~<>=| +\-]+", selector):
                raise ValueError("npm_lock_dependency_source_unsupported")
    for field in ("os", "cpu"):
        if field in value and (not isinstance(value[field], list) or not value[field]
                or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9_-]+", item)
                       for item in value[field])):
            raise ValueError("npm_lock_platform_metadata_unsupported")
    peers = value.get("peerDependenciesMeta", {})
    if not isinstance(peers, dict) or any(not re.fullmatch(PACKAGE_NAME, key)
            or not isinstance(item, dict) or set(item) != {"optional"}
            or type(item["optional"]) is not bool for key, item in peers.items()):
        raise ValueError("npm_lock_peer_metadata_unsupported")
    if "funding" in value:
        funding = value["funding"] if isinstance(value["funding"], list) else [value["funding"]]
        if any(not isinstance(item, dict) or "url" not in item or set(item) - {"type", "url"}
               or any(not isinstance(v, str) for v in item.values()) for item in funding):
            raise ValueError("npm_lock_funding_metadata_unsupported")
    if "license" in value and not isinstance(value["license"], str):
        raise ValueError("npm_lock_license_unsupported")


def locked_tarballs(package_raw: bytes, lock_raw: bytes) -> tuple[LockedNpmTarball, ...]:
    """Read the supported lock v3 shape without executing npm or any project script."""
    package, lock = strict_json(package_raw), strict_json(lock_raw)
    package_fields = {"name", "version", "private", "type", "scripts", "dependencies", "devDependencies"}
    if set(package) != package_fields or package["private"] is not True or package["type"] != "module":
        raise ValueError("npm_package_fields_unsupported")
    if (set(lock) != {"name", "version", "lockfileVersion", "requires", "packages"}
            or type(lock["lockfileVersion"]) is not int or lock["lockfileVersion"] != 3
            or lock["requires"] is not True or not isinstance(lock["packages"], dict)
            or len(lock["packages"]) != TARBALL_COUNT + 1):
        raise ValueError("npm_lock_format_unsupported")
    root = {key: package[key] for key in ("name", "version", "dependencies", "devDependencies")}
    if (lock["packages"].get("") != root or lock["name"] != root["name"]
            or lock["version"] != root["version"]):
        raise ValueError("npm_package_lock_root_mismatch")
    result = []
    for path, value in sorted(lock["packages"].items()):
        if not path:
            continue
        _metadata(value)
        result.append(LockedNpmTarball(package_path=path, version=value.get("version"),
            url=value.get("resolved"), integrity=value.get("integrity")))
    by_path = {item.package_path: item for item in result}
    for field in ("dependencies", "devDependencies"):
        if not isinstance(root[field], dict):
            raise ValueError("npm_root_dependencies_unsupported")
        for name, version in root[field].items():
            found = by_path.get("node_modules/" + name)
            if found is None or found.version != version:
                raise ValueError("npm_root_dependency_not_exactly_locked")
    return tuple(result)
