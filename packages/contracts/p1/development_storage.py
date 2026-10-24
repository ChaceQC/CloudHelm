"""Observed dedicated development storage; not a shared Runner resource ledger."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import UtcTimestamp

StorageId = Annotated[str, Field(pattern=r"^dev-storage-[a-f0-9]{32}$")]
StoragePurpose = Literal["git", "workspace", "candidate", "cache", "archive", "fixture"]
Bytes = Annotated[int, Field(ge=0, strict=True)]
InstanceRevision = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
MIN_STORAGE_BYTES = 32 * 1024**2
MAX_STORAGE_BYTES = 16 * 1024**3


class DevelopmentStorageRef(Contract):
    """A pinned trusted registration reference; this is not a grant of authority."""

    schema_revision: Literal["p1-development-storage-ref-r1"] = "p1-development-storage-ref-r1"
    storage_id: StorageId
    instance_revision: InstanceRevision
    purpose: StoragePurpose


class DevelopmentStorageRegistration(Contract):
    method_revision: Literal["p1-development-storage-r2", "p1-development-storage-r3"] = "p1-development-storage-r2"
    storage_id: StorageId
    instance_revision: InstanceRevision
    filesystem_uuid: Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")]
    owner_uid: Literal[1000] = 1000
    backing_file_bytes: Annotated[int, Field(ge=MIN_STORAGE_BYTES, le=MAX_STORAGE_BYTES, strict=True)]
    backing_device: Bytes
    backing_inode: Bytes
    created_at: UtcTimestamp
    scope: Literal["local_development_fixture_only", "local_controlled_development"] = (
        "local_development_fixture_only"
    )
    allowed_purposes: Annotated[tuple[StoragePurpose, ...], Field(min_length=1, max_length=6)] = ("fixture",)
    admission_safety_bytes: Annotated[int, Field(ge=64 * 1024, le=16 * 1024**2, strict=True)] = 1024**2
    managed_docker: bool = False

    @model_validator(mode="after")
    def supported_scope(self):
        if len(set(self.allowed_purposes)) != len(self.allowed_purposes):
            raise ValueError("development_storage_duplicate_purpose")
        fixture = self.scope == "local_development_fixture_only"
        if self.managed_docker and (fixture or self.method_revision != "p1-development-storage-r3"):
            raise ValueError("managed_docker_requires_controlled_storage_r3")
        if ((fixture and (self.backing_file_bytes != MIN_STORAGE_BYTES or self.allowed_purposes != ("fixture",)))
                or (not fixture and "fixture" in self.allowed_purposes)):
            raise ValueError("development_storage_scope_mismatch")
        return self


class DevelopmentStorageSnapshot(Contract):
    registration: DevelopmentStorageRegistration
    observed_at: UtcTimestamp
    purpose: StoragePurpose
    source_directory: str
    mount_id: Annotated[int, Field(gt=0, strict=True)]
    mount_source: Annotated[str, Field(pattern=r"^/dev/loop[0-9]+$")]
    mount_device: str
    mount_namespace: str
    mount_options: tuple[str, ...]
    backing_allocated_bytes: Bytes
    accounted_backing_bytes: Bytes
    filesystem_capacity_bytes: Bytes
    filesystem_free_bytes: Bytes
    filesystem_available_bytes: Bytes
    retained_bytes_including_metadata: Bytes
    admission_safety_bytes: Bytes
    allocatable_bytes: Bytes
    hard_boundary: Literal["fixed_regular_file_ext4"] = "fixed_regular_file_ext4"
    accounting_scope: Literal["whole_backing_file_remains_charged_after_stop"] = (
        "whole_backing_file_remains_charged_after_stop"
    )

    @model_validator(mode="after")
    def consistent_bytes(self):
        if (self.filesystem_available_bytes > self.filesystem_free_bytes
                or self.filesystem_free_bytes > self.filesystem_capacity_bytes
                or self.retained_bytes_including_metadata != (
                    self.filesystem_capacity_bytes - self.filesystem_free_bytes)
                or self.allocatable_bytes != max(
                    0, self.filesystem_available_bytes - self.admission_safety_bytes)
                or self.admission_safety_bytes != self.registration.admission_safety_bytes
                or self.accounted_backing_bytes != self.registration.backing_file_bytes
                or self.filesystem_capacity_bytes > self.accounted_backing_bytes
                or self.backing_allocated_bytes < self.registration.backing_file_bytes):
            raise ValueError("development_storage_measurement_inconsistent")
        return self
