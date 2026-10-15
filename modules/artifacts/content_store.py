"""Trusted internal artifact storage; host paths are never public API inputs."""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from typing import BinaryIO, Iterator
from uuid import uuid4

from modules.artifacts.content_files import (
    ArtifactRoot, directory_at, new_file, publish_directory, regular_at, remove_staging,
    source_archive,
)
from modules.artifacts.errors import ArtifactContentError
from modules.artifacts.oci_archive import inspect_oci_archive
from packages.contracts.p1.build_artifacts import (
    ArtifactContent, ArtifactLimits, MAX_RECEIPT_BYTES, artifact_content_bytes,
)


@contextmanager
def _io_errors():
    try:
        yield
    except OSError:
        raise ArtifactContentError("artifact_storage_unavailable") from None


def _exists(root: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _storage_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"oci-[0-9a-f]{64}", value):
        raise ArtifactContentError("artifact_storage_id_invalid")


class ArtifactStore:
    """One service-owned Linux root; caller authenticates and admits operations.

    The root and source parent must already be private directories owned by the
    effective service UID. Neither belongs in a candidate mount. Limits bound
    accepted content; they do not claim a physical disk quota or business grant.
    Content-addressed directories are atomically published as 0500, files as
    0400. Query/open rehash the retained archive and compare canonical receipts.
    """

    def __init__(self, content_root: str | os.PathLike[str], *, limits: ArtifactLimits | None = None):
        try:
            if limits is not None and type(limits) is not ArtifactLimits:
                raise ValueError("invalid limits type")
            self.limits = ArtifactLimits.model_validate((limits or ArtifactLimits()).model_dump())
        except ValueError:
            raise ArtifactContentError("artifact_limits_invalid") from None
        with _io_errors():
            self._root = ArtifactRoot(content_root)

    @contextmanager
    def _verified(self, root: int, storage_id: str):
        if not _exists(root, storage_id):
            raise ArtifactContentError("artifact_not_found")
        with directory_at(root, storage_id, readonly=True) as stored:
            if set(os.listdir(stored)) != {"archive.oci.tar", "receipt.json"}:
                raise ArtifactContentError("artifact_storage_members_mismatch")
            with regular_at(stored, "receipt.json", MAX_RECEIPT_BYTES, readonly=True) as metadata:
                raw = metadata.read(MAX_RECEIPT_BYTES + 1)
            try:
                receipt = ArtifactContent.model_validate_json(raw)
                if artifact_content_bytes(receipt) != raw or receipt.storage_id != storage_id:
                    raise ValueError("noncanonical receipt")
            except ValueError:
                raise ArtifactContentError("artifact_receipt_invalid") from None
            with regular_at(stored, "archive.oci.tar", self.limits.max_archive_bytes, readonly=True) as archive:
                actual = inspect_oci_archive(archive, self.limits)
                if actual != receipt:
                    raise ArtifactContentError("artifact_receipt_mismatch")
                yield receipt, archive

    def publish(self, archive_file: str | os.PathLike[str], *,
                expected_archive_digest: str | None = None) -> ArtifactContent:
        """Intake a controlled regular file; never accept an untrusted host path."""
        if expected_archive_digest is not None and (
            not isinstance(expected_archive_digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_archive_digest)
        ):
            raise ArtifactContentError("artifact_expected_digest_invalid")
        with _io_errors(), self._root.exclusive() as root:
            staged, published = "stage-" + uuid4().hex, False
            os.mkdir(staged, 0o700, dir_fd=root)
            try:
                with directory_at(root, staged) as staging:
                    receipt = self._stage(staging, archive_file, expected_archive_digest)
                    if _exists(root, receipt.storage_id):
                        with self._verified(root, receipt.storage_id) as (existing, _):
                            if existing != receipt:
                                raise ArtifactContentError("artifact_publication_conflict")
                            return existing
                    os.fchmod(staging, 0o500)
                    os.fsync(staging)
                publish_directory(root, staged, receipt.storage_id)
                published = True
                return receipt
            finally:
                if not published and _exists(root, staged):
                    remove_staging(root, staged)

    def _stage(self, staging, archive_file, expected_digest):
        with source_archive(archive_file, self.limits.max_archive_bytes) as source:
            with new_file(staging, "archive.oci.tar") as archive:
                digest, size = hashlib.sha256(), 0
                while chunk := source.read(65536):
                    size += len(chunk)
                    if size > self.limits.max_archive_bytes:
                        raise ArtifactContentError("artifact_archive_too_large")
                    archive.write(chunk)
                    digest.update(chunk)
                archive.flush()
                copied_digest = "sha256:" + digest.hexdigest()
                if expected_digest is not None and expected_digest != copied_digest:
                    raise ArtifactContentError("artifact_expected_digest_mismatch")
                receipt = inspect_oci_archive(archive, self.limits)
                if receipt.archive_digest != copied_digest or receipt.archive_bytes != size:
                    raise ArtifactContentError("artifact_content_changed")
        with new_file(staging, "receipt.json") as metadata:
            metadata.write(artifact_content_bytes(receipt))
        os.fsync(staging)
        return receipt

    def query(self, storage_id: str) -> ArtifactContent:
        _storage_id(storage_id)
        with _io_errors(), self._root.exclusive() as root:
            with self._verified(root, storage_id) as (receipt, _):
                return receipt

    @contextmanager
    def open_archive(self, storage_id: str) -> Iterator[BinaryIO]:
        """Yield the verified O_RDONLY inode at offset zero, never a host pathname.

        The root lock remains held until consumption finishes, with an inode
        metadata check on exit. The consumer must separately verify Docker facts.
        """
        _storage_id(storage_id)
        with _io_errors(), self._root.exclusive() as root:
            with self._verified(root, storage_id) as (_, archive):
                yield archive

    def close(self) -> None:
        self._root.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
