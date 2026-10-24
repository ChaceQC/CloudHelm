"""P1 resource protocol; P0 vectors/identities retain their original semantics."""

from datetime import timedelta
from typing import Literal, Self

import hashlib
import rfc8785
from pydantic import AwareDatetime, Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.resource_contracts import (
    AllocationIdentity, HostResourcePool, ResourceAdjustment, ResourceAllocation,
    ResourceReleaseEvidence, ResourceRequest, ResourceVector, project_release,
)
from .development_storage import DevelopmentStorageRef

PROTOCOL = "p1-resources-r1"
LIFECYCLE_PROTOCOL = "p1-resources-r2"
BACKEND = "linux-systemd-docker-scratch-r1"
DEVELOPMENT_BACKEND = "linux-systemd-docker-development-r1"
STORAGE_BACKEND = "linux-development-storage-r1"
Backend = Literal[BACKEND, DEVELOPMENT_BACKEND, STORAGE_BACKEND]


def canonical_digest(value: dict) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def resource_request_digest(request: ResourceRequest) -> str:
    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


class RunnerRegistration(Contract):
    protocol_revision: Literal[PROTOCOL, LIFECYCLE_PROTOCOL] = PROTOCOL
    executor_instance_id: Identifier
    host_resource_pool_id: Identifier
    physical_host_id: Identifier
    hub_incarnation: Identifier
    resource_generation: Revision
    platform: Literal["linux/amd64"] = "linux/amd64"
    backend: Backend = BACKEND
    maximum: ResourceVector
    cpu_period_us: int = Field(strict=True, ge=1000, le=1000000)
    capability_evidence_ref: Identifier
    image_id: Digest | None = None
    recipe_digest: Digest
    storage: DevelopmentStorageRef | None = None
    storage_owner_reservation_id: Identifier | None = None

    @model_validator(mode="after")
    def storage_binding(self) -> Self:
        if self.backend != BACKEND:
            if self.protocol_revision != LIFECYCLE_PROTOCOL or self.storage is None or self.storage.purpose != "workspace":
                raise ValueError("resource_development_requires_r2_storage_binding")
            if self.backend == DEVELOPMENT_BACKEND and self.storage_owner_reservation_id is None:
                raise ValueError("resource_development_requires_storage_owner")
            if self.image_id is not None:
                raise ValueError("resource_managed_backend_has_no_workload_image")
            if self.backend == STORAGE_BACKEND and self.maximum != ResourceVector(disk_bytes=self.maximum.disk_bytes):
                raise ValueError("resource_storage_capability_is_disk_only")
        elif self.storage is not None or self.storage_owner_reservation_id is not None:
            raise ValueError("scratch_cannot_bind_persistent_storage")
        elif self.image_id is None:
            raise ValueError("scratch_requires_fixed_image_identity")
        return self


class PoolRegistration(Contract):
    protocol_revision: Literal[PROTOCOL] = PROTOCOL
    pool: HostResourcePool
    hub_incarnation: Identifier
    resource_generation: Revision


class ReserveResourcesRequest(Contract):
    protocol_revision: Literal[PROTOCOL, LIFECYCLE_PROTOCOL] = PROTOCOL
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    expires_at_utc: AwareDatetime
    resources: ResourceRequest
    backend: Backend = BACKEND

    @model_validator(mode="after")
    def canonical_request(self) -> Self:
        if self.expires_at_utc.utcoffset() != timedelta(0):
            raise ValueError("resource_deadline_requires_utc")
        if self.resources.request_digest != resource_request_digest(self.resources):
            raise ValueError("resource_request_digest_mismatch")
        limits = self.resources.hard_limits
        if self.backend == STORAGE_BACKEND:
            if limits != ResourceVector(disk_bytes=limits.disk_bytes) or limits.disk_bytes <= 0:
                raise ValueError("storage_owner_requires_only_positive_disk_limit")
        elif min(limits.memory_mib, limits.cpu_millicores, limits.pids) <= 0:
            raise ValueError("resource_group_requires_positive_process_limits")
        if self.backend == BACKEND and limits.disk_bytes < 2 * 1024**2:
            raise ValueError("scratch_disk_limit_too_small")
        return self


class ReservationResult(Contract):
    command_id: Identifier
    task_id: Identifier
    allocation: ResourceAllocation


class ExecutorReceipt(Contract):
    protocol_revision: Literal[PROTOCOL, LIFECYCLE_PROTOCOL] = PROTOCOL
    identity: AllocationIdentity
    request_digest: Digest
    sequence: Revision
    state: Literal["accepted", "launching", "running", "unknown", "closed_unstarted", "stopped"]
    process_binding: Identifier | None = None
    disk_reclaimed: bool = False
    disk_remaining_bytes: int | None = Field(default=None, strict=True, ge=0, le=9007199254740991)
    evidence: dict[str, str | int | bool] = Field(default_factory=dict, max_length=24)

    @model_validator(mode="after")
    def terminal_facts(self) -> Self:
        if self.state == "closed_unstarted" and (self.process_binding is not None or not self.disk_reclaimed):
            raise ValueError("closed_unstarted_requires_durable_start_fence")
        if self.state in {"running", "stopped"} and self.process_binding is None:
            raise ValueError("physical_receipt_requires_process_binding")
        if self.disk_reclaimed and self.state not in {"closed_unstarted", "stopped"}:
            raise ValueError("disk_release_requires_closed_execution")
        if self.disk_remaining_bytes is not None:
            if self.protocol_revision != LIFECYCLE_PROTOCOL or self.state not in {"closed_unstarted", "stopped"}:
                raise ValueError("disk_observation_requires_closed_r2_receipt")
            if self.disk_reclaimed != (self.disk_remaining_bytes == 0):
                raise ValueError("disk_reclamation_and_remaining_bytes_conflict")
        return self


class ResourceAdjustmentResult(Contract):
    resource_adjustment_id: Identifier
    request_digest: Digest
    status: Literal["unchanged", "rejected"]
    code: Identifier
    allocation: ResourceAllocation


def adjustment_digest(adjustment: ResourceAdjustment) -> str:
    return canonical_digest(adjustment.model_dump(mode="json", exclude={"request_digest"}))


def allocation_from_receipt(current: ResourceAllocation, receipt: ExecutorReceipt) -> ResourceAllocation:
    """Project trusted physical facts identically on both ledgers; no I/O or authority."""
    if receipt.identity != current.identity or receipt.request_digest != current.creation_request_digest:
        raise ValueError("resource_receipt_identity_mismatch")
    closed = receipt.state in {"closed_unstarted", "stopped"}
    if current.state == "releasing" and current.hard_limits == ResourceVector() and not closed:
        raise ValueError("resource_closed_execution_cannot_reopen")
    values = {"state": "active" if receipt.state == "running" else
              "reserved" if receipt.state == "accepted" else "orphaned"}
    if closed:
        remaining = 0 if receipt.disk_reclaimed else receipt.disk_remaining_bytes
        projection = project_release(current, ResourceReleaseEvidence(
            identity=current.identity, expected_allocation_revision=current.allocation_revision,
            closure="closed_unstarted" if receipt.state == "closed_unstarted" else "group_stopped",
            closure_evidence_ref="executor-receipt-" + str(receipt.sequence),
            disk_remaining_bytes=remaining,
            disk_evidence_ref="executor-disk-" + str(receipt.sequence) if remaining is not None else None,
        ))
        values = {"state": "released" if projection.remaining_accounted_vector == ResourceVector() else "releasing",
                  "accounted_vector": projection.remaining_accounted_vector,
                  "hard_limits": projection.effective_hard_limits}
    if current.state == "released" and values["state"] != "released":
        raise ValueError("resource_released_allocation_cannot_reopen")
    return ResourceAllocation.model_validate(current.model_dump() | values)


def match_runner(registration: RunnerRegistration, request: ResourceRequest, backend: str) -> None:
    identity = request.identity
    if (identity.executor_instance_id != registration.executor_instance_id
            or identity.host_resource_pool_id != registration.host_resource_pool_id
            or identity.hub_incarnation != registration.hub_incarnation
            or identity.resource_generation != registration.resource_generation
            or identity.cpu_period_us != registration.cpu_period_us or backend != registration.backend
            or identity.resource_group_digest != registration.recipe_digest):
        raise ValueError("resource_runner_identity_or_capability_mismatch")
    if any(getattr(request.hard_limits, name) > getattr(registration.maximum, name)
           for name in ResourceVector.model_fields):
        raise ValueError("resource_group_exceeds_runner_capability")
