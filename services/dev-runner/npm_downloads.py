"""Publish immutable fixed-frontend tarball seeds, separately from installation."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from modules.artifacts.content_files import (
    ArtifactRoot, directory_at, new_file, publish_directory, regular_at,
)
from modules.artifacts.errors import ArtifactContentError
from packages.contracts.p1.npm_cache import (
    INPUT_BYTES, LOCK_DIGEST, MAX_MANIFEST_BYTES, MAX_TARBALL_BYTES, MAX_TARBALL_TOTAL,
    PACKAGE_DIGEST, LockedNpmTarball, NpmDownloadSpec, NpmSeedManifest, NpmSeedReceipt,
    NpmSeedTarball, canonical, locked_tarballs, npm_seed_id, strict_json,
)

from .npm_download_io import NpmDownloadError, RegistryDownloads, source_inputs


def _fixed_inputs(inputs: dict[str, bytes]) -> tuple[LockedNpmTarball, ...]:
    for name, digest in (("package.json", PACKAGE_DIGEST), ("package-lock.json", LOCK_DIGEST)):
        if "sha256:" + hashlib.sha256(inputs[name]).hexdigest() != digest:
            raise NpmDownloadError("npm_fixed_input_digest_mismatch")
    if sum(map(len, inputs.values())) != INPUT_BYTES:
        raise NpmDownloadError("npm_fixed_input_bytes_mismatch")
    return locked_tarballs(inputs["package.json"], inputs["package-lock.json"])


def _write(directory: int, name: str, data: bytes) -> None:
    with new_file(directory, name) as stream:
        stream.write(data)


def _read(directory: int, name: str, limit: int) -> bytes:
    with regular_at(directory, name, limit, readonly=True) as stream:
        return stream.read(limit + 1)


def _remove_stage(root: int, name: str, allowed: set[str]) -> None:
    # Only this invocation's private staging directory and predetermined names.
    with directory_at(root, name) as directory:
        os.fchmod(directory, 0o700)
        if set(os.listdir(directory)) - allowed:
            raise NpmDownloadError("npm_stage_cleanup_scope_invalid")
        for entry in os.listdir(directory):
            os.unlink(entry, dir_fd=directory)
    os.rmdir(name, dir_fd=root)
    os.fsync(root)


class NpmDownloadStore:
    """Service-owned Linux root. Logical byte bounds provide no physical quota."""

    def __init__(self, root: Path):
        try:
            self.root = ArtifactRoot(root)
        except (OSError, ArtifactContentError):
            raise NpmDownloadError("npm_private_linux_cache_root_required") from None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.root.close()

    @staticmethod
    def _spec(spec: NpmDownloadSpec, cache_id: str | None = None) -> NpmDownloadSpec:
        try:
            checked = NpmDownloadSpec.model_validate(spec.model_dump(mode="python"))
        except (ValidationError, AttributeError):
            raise NpmDownloadError("npm_cache_spec_unsupported") from None
        if cache_id is not None and cache_id != npm_seed_id(checked):
            raise NpmDownloadError("npm_cache_key_mismatch")
        return checked

    def _verify_directory(self, directory: int, spec: NpmDownloadSpec, *, cache_hit: bool,
                          expected_manifest_digest: str | None = None) -> NpmSeedReceipt:
        inputs = {name: _read(directory, name, 1024 * 1024)
                  for name in ("package.json", "package-lock.json")}
        locked = _fixed_inputs(inputs)
        raw = _read(directory, "manifest.json", MAX_MANIFEST_BYTES)
        manifest = NpmSeedManifest.model_validate(strict_json(raw))
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if (canonical(manifest) != raw or manifest.spec != spec
                or manifest.cache_id != npm_seed_id(spec)
                or (expected_manifest_digest is not None and digest != expected_manifest_digest)):
            raise NpmDownloadError("npm_cache_manifest_identity_mismatch")
        expected_names = {"package.json", "package-lock.json", "manifest.json"}
        expected_names.update(item.blob_name for item in locked)
        if set(os.listdir(directory)) != expected_names:
            raise NpmDownloadError("npm_cache_files_mismatch")
        for expected, entry in zip(locked, manifest.tarballs, strict=True):
            identity = entry.model_dump(include={"package_path", "version", "url", "integrity"})
            if expected.model_dump() != identity:
                raise NpmDownloadError("npm_cache_lock_tarball_mismatch")
            sha256, sha512, size = hashlib.sha256(), hashlib.sha512(), 0
            with regular_at(directory, entry.filename, MAX_TARBALL_BYTES, readonly=True) as stream:
                while chunk := stream.read(65536):
                    size += len(chunk)
                    sha256.update(chunk)
                    sha512.update(chunk)
            if (size != entry.bytes or "sha256:" + sha256.hexdigest() != entry.sha256
                    or "sha512:" + sha512.hexdigest() != entry.sha512):
                raise NpmDownloadError("npm_cache_tarball_content_mismatch")
        return NpmSeedReceipt(manifest=manifest, manifest_digest=digest, manifest_bytes=len(raw),
            seed_bytes=manifest.tarball_bytes + INPUT_BYTES + len(raw), cache_hit=cache_hit)

    def verify(self, spec: NpmDownloadSpec, cache_id: str | None = None, *,
               expected_manifest_digest: str | None = None) -> NpmSeedReceipt:
        spec = self._spec(spec, cache_id)
        try:
            with self.root.exclusive() as root:
                try:
                    os.stat(npm_seed_id(spec), dir_fd=root, follow_symlinks=False)
                except FileNotFoundError:
                    raise NpmDownloadError("npm_seed_unavailable") from None
                with directory_at(root, npm_seed_id(spec), readonly=True) as directory:
                    return self._verify_directory(directory, spec, cache_hit=True,
                        expected_manifest_digest=expected_manifest_digest)
        except NpmDownloadError:
            raise
        except (OSError, ArtifactContentError, ValueError):
            raise NpmDownloadError("npm_cache_verification_rejected") from None

    def prepare(self, spec: NpmDownloadSpec, frontend: Path, *,
                cache_id: str | None = None) -> NpmSeedReceipt:
        spec = self._spec(spec, cache_id)
        try:
            inputs = source_inputs(frontend)
            locked = _fixed_inputs(inputs)
            with self.root.exclusive() as root:
                identity = npm_seed_id(spec)
                try:
                    os.stat(identity, dir_fd=root, follow_symlinks=False)
                except FileNotFoundError:
                    return self._prepare_new(root, spec, inputs, locked)
                with directory_at(root, identity, readonly=True) as directory:
                    return self._verify_directory(directory, spec, cache_hit=True)
        except NpmDownloadError:
            raise
        except (OSError, ArtifactContentError, ValueError):
            raise NpmDownloadError("npm_seed_preparation_rejected") from None

    def _prepare_new(self, root: int, spec: NpmDownloadSpec, inputs: dict,
                     locked: tuple[LockedNpmTarball, ...]) -> NpmSeedReceipt:
        stage = "npm-stage-" + uuid4().hex
        allowed = {"package.json", "package-lock.json", "manifest.json"}
        allowed.update(item.blob_name for item in locked)
        os.mkdir(stage, 0o700, dir_fd=root)
        published = False
        downloader = None
        try:
            downloader = RegistryDownloads()
            with directory_at(root, stage) as directory:
                for name, raw in inputs.items():
                    _write(directory, name, raw)
                entries, total = [], 0
                for item in locked:
                    with new_file(directory, item.blob_name) as stream:
                        entry = NpmSeedTarball(**downloader.fetch(item, stream, MAX_TARBALL_TOTAL - total))
                    entries.append(entry)
                    total += entry.bytes
                manifest = NpmSeedManifest(cache_id=npm_seed_id(spec), spec=spec,
                    created_at=datetime.now(UTC), tarballs=tuple(entries), tarball_bytes=total)
                _write(directory, "manifest.json", canonical(manifest))
                os.fchmod(directory, 0o500)
                os.fsync(directory)
                receipt = self._verify_directory(directory, spec, cache_hit=False)
            publish_directory(root, stage, npm_seed_id(spec))
            published = True
            return receipt
        finally:
            if downloader is not None:
                downloader.close()
            if not published:
                _remove_stage(root, stage, allowed)
