"""Content receipts for one OCI image; no BuildRun or runtime-success claims."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

import rfc8785
from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest
from packages.contracts.p0.engineering_contracts import EngineeringRef

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar"
OCI_LAYER_GZIP = "application/vnd.oci.image.layer.v1.tar+gzip"
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 8192
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_LAYERS = 2048
MAX_RECEIPT_BYTES = 1024 * 1024
ArtifactStorageId = Annotated[str, Field(pattern=r"^oci-[0-9a-f]{64}$")]


class ArtifactLimits(Contract):
    """Logical intake bounds, independent of Runner physical storage quotas."""

    max_archive_bytes: int = Field(default=1024**3, strict=True, ge=1024, le=MAX_ARCHIVE_BYTES)
    max_members: int = Field(default=4096, strict=True, ge=4, le=MAX_MEMBERS)
    max_json_bytes: int = Field(default=4 * 1024 * 1024, strict=True, ge=256, le=MAX_JSON_BYTES)
    max_layers: int = Field(default=1024, strict=True, ge=0, le=MAX_LAYERS)


class OciDescriptor(Contract):
    media_type: Literal[
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.config.v1+json",
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
    ]
    digest: Digest
    size_bytes: int = Field(strict=True, ge=0, le=MAX_ARCHIVE_BYTES)


class ArtifactContent(Contract):
    schema_revision: Literal["p1-artifact-content-r1"] = "p1-artifact-content-r1"
    storage_id: ArtifactStorageId
    archive_digest: Digest
    archive_bytes: int = Field(strict=True, ge=1024, le=MAX_ARCHIVE_BYTES)
    platform: Literal["linux/amd64"] = "linux/amd64"
    manifest: OciDescriptor
    config: OciDescriptor
    image_id: Digest
    layers: tuple[OciDescriptor, ...] = Field(max_length=MAX_LAYERS)

    @model_validator(mode="after")
    def check_content_identity(self):
        if self.storage_id != "oci-" + self.archive_digest.removeprefix("sha256:"):
            raise ValueError("artifact_storage_identity_mismatch")
        if self.manifest.media_type != OCI_MANIFEST or self.config.media_type != OCI_CONFIG:
            raise ValueError("artifact_metadata_media_type_invalid")
        if self.image_id != self.config.digest:
            raise ValueError("artifact_image_identity_mismatch")
        if any(layer.media_type not in {OCI_LAYER, OCI_LAYER_GZIP} for layer in self.layers):
            raise ValueError("artifact_layer_media_type_invalid")
        descriptors = (self.manifest, self.config, *self.layers)
        by_digest = {entry.digest: entry for entry in descriptors}
        if any(by_digest[entry.digest] != entry for entry in descriptors):
            raise ValueError("artifact_descriptor_identity_conflict")
        return self


def artifact_content_bytes(content: ArtifactContent) -> bytes:
    """Versioned receipt metadata, separate from archive/config/blob digests."""
    if type(content) is not ArtifactContent:
        raise TypeError("artifact_content_type_invalid")
    encoded = rfc8785.dumps(content.model_dump(mode="json"))
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise ValueError("artifact_receipt_too_large")
    return encoded


def artifact_content_ref(content: ArtifactContent) -> EngineeringRef:
    digest = "sha256:" + hashlib.sha256(artifact_content_bytes(content)).hexdigest()
    return EngineeringRef(
        kind="artifact", object_id=content.storage_id, revision=content.schema_revision,
        authority="artifacts", digest=digest, digest_algorithm="sha256",
    )
