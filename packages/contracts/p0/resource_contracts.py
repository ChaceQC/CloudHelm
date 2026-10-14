"""Bounded P0 resource contracts and pure arithmetic; no authoritative ledger."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from .decision_common import Contract, Digest, Identifier, ProtocolRevision, Revision

Quantity = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]


class ResourceVector(Contract):
    memory_mib: Quantity = 0
    cpu_millicores: Quantity = 0
    disk_bytes: Quantity = 0
    pids: Quantity = 0
    heavy_slots: Quantity = 0
    preview_slots: Quantity = 0


def vector_max(left: ResourceVector, right: ResourceVector) -> ResourceVector:
    return ResourceVector(**{k: max(getattr(left, k), getattr(right, k))
                             for k in ResourceVector.model_fields})


def vector_sum(vectors: tuple[ResourceVector, ...]) -> ResourceVector:
    return ResourceVector(**{k: sum(getattr(v, k) for v in vectors)
                             for k in ResourceVector.model_fields})


def _within(value: ResourceVector, ceiling: ResourceVector) -> bool:
    return all(getattr(value, k) <= getattr(ceiling, k) for k in ResourceVector.model_fields)


class ResourceLimits(Contract):
    accounted_vector: ResourceVector
    hard_limits: ResourceVector

    @model_validator(mode="after")
    def enforce_accounting(self) -> Self:
        if not _within(self.hard_limits, self.accounted_vector):
            raise ValueError("hard_limits_exceed_accounted_vector")
        return self


class AllocationIdentity(Contract):
    reservation_id: Identifier
    operation_id: Identifier
    resource_group_id: Identifier
    resource_group_digest: Digest
    host_resource_pool_id: Identifier
    executor_instance_id: Identifier
    hub_incarnation: Identifier
    resource_generation: Revision
    cpu_period_us: Annotated[int, Field(strict=True, gt=0, le=9007199254740991)]
    conflict_keys: tuple[Identifier, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def canonical_conflicts(self) -> Self:
        if self.conflict_keys != tuple(sorted(set(self.conflict_keys))):
            raise ValueError("conflict_keys_must_be_sorted_and_unique")
        return self


class HostResourcePool(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    host_resource_pool_id: Identifier
    physical_host_id: Identifier
    executor_instance_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    capacity_revision: Revision
    configured_budget: ResourceVector
    measured_allocatable_capacity: ResourceVector | None = None
    unknown_occupancy_upper_bound: ResourceVector | None = None
    host_identity_evidence_ref: Identifier | None = None
    capacity_evidence_ref: Identifier | None = None
    group_limits_evidence_ref: Identifier | None = None

    @model_validator(mode="after")
    def unique_executors(self) -> Self:
        if len(set(self.executor_instance_ids)) != len(self.executor_instance_ids):
            raise ValueError("duplicate_executor_instance")
        if self.configured_budget.heavy_slots > 1 or self.configured_budget.preview_slots > 1:
            raise ValueError("r1_shared_pool_allows_at_most_one_slot_per_category")
        return self


class ResourceRequest(ResourceLimits):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    identity: AllocationIdentity
    request_digest: Digest
    request_vector: ResourceVector

    @model_validator(mode="after")
    def equal_memory_and_pids(self) -> Self:
        for key in ("memory_mib", "pids"):
            if not (getattr(self.request_vector, key) == getattr(self.accounted_vector, key)
                    == getattr(self.hard_limits, key)):
                raise ValueError("memory_and_pids_require_request_accounted_limit_equality")
        return self


class ResourceAllocation(ResourceLimits):
    identity: AllocationIdentity
    creation_request_digest: Digest
    allocation_revision: Revision
    state: Literal["reserved", "active", "releasing", "orphaned", "released"]
    pending_resource_adjustment_id: Identifier | None = None

    @model_validator(mode="after")
    def released_is_empty(self) -> Self:
        if self.state == "released" and (
            self.accounted_vector != ResourceVector() or self.pending_resource_adjustment_id
        ):
            raise ValueError("released_allocation_must_have_no_charge_or_pending_adjustment")
        return self


class ResourceAdjustment(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    resource_adjustment_id: Identifier
    request_digest: Digest
    identity: AllocationIdentity
    expected_allocation_revision: Revision
    target: ResourceLimits

    @model_validator(mode="after")
    def target_memory_and_pids(self) -> Self:
        for key in ("memory_mib", "pids"):
            if getattr(self.target.accounted_vector, key) != getattr(self.target.hard_limits, key):
                raise ValueError("target_memory_and_pids_require_accounted_limit_equality")
        return self


class PendingAdjustmentAccounting(Contract):
    adjustment: ResourceAdjustment
    previous_accounted_vector: ResourceVector
    state: Literal["pending", "unknown"]
    allocation_revision: Revision
    accounted_vector: ResourceVector

    @model_validator(mode="after")
    def preserve_conservative_hold(self) -> Self:
        expected = vector_max(self.previous_accounted_vector, self.adjustment.target.accounted_vector)
        if self.accounted_vector != expected:
            raise ValueError("pending_adjustment_requires_dimensionwise_maximum")
        if self.allocation_revision != self.adjustment.expected_allocation_revision:
            raise ValueError("pending_adjustment_cannot_advance_confirmed_revision")
        return self


class DiskRetentionTransfer(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    transfer_id: Identifier
    request_digest: Digest
    identity: AllocationIdentity
    allocation_revision: Revision
    retained_object_id: Identifier
    retained_bytes: Quantity
    retention_limit_bytes: Quantity
    accounting_mode: Literal["ledger"] = "ledger"
    observed_at_utc: AwareDatetime
    transfer_evidence_ref: Identifier

    @model_validator(mode="after")
    def bounded_retention(self) -> Self:
        if not 0 < self.retained_bytes <= self.retention_limit_bytes:
            raise ValueError("retention_must_have_a_positive_bounded_byte_count")
        if self.observed_at_utc.utcoffset() != timedelta(0):
            raise ValueError("retention_observation_requires_utc")
        return self


class ResourceReleaseEvidence(Contract):
    identity: AllocationIdentity
    expected_allocation_revision: Revision
    closure: Literal["unknown", "group_stopped", "closed_unstarted"]
    closure_evidence_ref: Identifier | None = None
    disk_remaining_bytes: Quantity | None = None
    disk_evidence_ref: Identifier | None = None
    retention_transfer: DiskRetentionTransfer | None = None


class ReleaseProjection(Contract):
    remaining_accounted_vector: ResourceVector
    effective_hard_limits: ResourceVector
    transferred_retained_bytes: Quantity = 0


def validate_admission(
    pool: HostResourcePool, allocations: tuple[ResourceAllocation, ...],
    request: ResourceRequest, retained: tuple[DiskRetentionTransfer, ...] = (),
    pending_adjustments: tuple[PendingAdjustmentAccounting, ...] = (),
) -> None:
    """Validate supplied snapshots, not authorization, evidence authenticity or atomicity."""
    if (pool.measured_allocatable_capacity is None or pool.unknown_occupancy_upper_bound is None
            or not all((pool.host_identity_evidence_ref, pool.capacity_evidence_ref,
                        pool.group_limits_evidence_ref))):
        raise ValueError("resource_environment_or_unknown_occupancy_unverified")
    identities = [request.identity, *(a.identity for a in allocations), *(r.identity for r in retained)]
    if any(i.host_resource_pool_id != pool.host_resource_pool_id
           or i.executor_instance_id not in pool.executor_instance_ids for i in identities):
        raise ValueError("shared_pool_or_registered_executor_mismatch")
    allocation_ids = [a.identity.reservation_id for a in allocations]
    if len(set(allocation_ids)) != len(allocation_ids) or request.identity.reservation_id in allocation_ids:
        raise ValueError("new_admission_requires_unique_reservation_identity_after_deduplication")
    transfer_ids = [r.transfer_id for r in retained]
    object_ids = [r.retained_object_id for r in retained]
    source_ids = [r.identity.reservation_id for r in retained]
    if any(len(set(ids)) != len(ids) for ids in (transfer_ids, object_ids, source_ids)):
        raise ValueError("retained_bytes_have_duplicate_ownership")
    if request.identity.reservation_id in source_ids:
        raise ValueError("retained_source_reservation_identity_cannot_be_reused")
    pending = {p.adjustment.resource_adjustment_id: p for p in pending_adjustments}
    expected_pending = {a.pending_resource_adjustment_id for a in allocations
                        if a.pending_resource_adjustment_id is not None}
    if len(pending) != len(pending_adjustments) or set(pending) != expected_pending:
        raise ValueError("pending_adjustment_snapshot_set_mismatch")
    for allocation in allocations:
        if allocation.pending_resource_adjustment_id is not None:
            hold = pending[allocation.pending_resource_adjustment_id]
            if (hold.adjustment.identity != allocation.identity or hold.allocation_revision != allocation.allocation_revision
                    or hold.accounted_vector != allocation.accounted_vector):
                raise ValueError("pending_adjustment_snapshot_does_not_match_allocation")
        if allocation.state != "released" and set(allocation.identity.conflict_keys).intersection(request.identity.conflict_keys):
            raise ValueError("resource_conflict")
        if allocation.accounted_vector.disk_bytes and any(
            r.identity.reservation_id == allocation.identity.reservation_id for r in retained
        ):
            raise ValueError("full_disk_transfer_cannot_also_charge_source_allocation")
    capacity = ResourceVector(**{k: min(getattr(pool.configured_budget, k),
                                       getattr(pool.measured_allocatable_capacity, k))
                                 for k in ResourceVector.model_fields})
    charged = vector_sum((*(a.accounted_vector for a in allocations),
                          ResourceVector(disk_bytes=sum(r.retained_bytes for r in retained)),
                          pool.unknown_occupancy_upper_bound, request.accounted_vector))
    if not _within(charged, capacity):
        raise ValueError("shared_host_capacity_exceeded")


def validate_new_adjustment(current: ResourceAllocation, adjustment: ResourceAdjustment) -> None:
    """Called only after persistent identity/digest lookup; r1 rejects in-place changes."""
    if current.identity != adjustment.identity:
        raise ValueError("adjustment_cannot_replace_allocation_identity")
    if current.allocation_revision != adjustment.expected_allocation_revision:
        raise ValueError("allocation_revision_conflict")
    if current.pending_resource_adjustment_id is not None:
        raise ValueError("resource_adjustment_already_pending")
    if current.state == "released":
        raise ValueError("allocation_closed")
    if (current.accounted_vector, current.hard_limits) != (
        adjustment.target.accounted_vector, adjustment.target.hard_limits
    ):
        raise ValueError("in_place_resource_adjustment_unsupported_stop_then_reallocate")


def project_release(current: ResourceAllocation, evidence: ResourceReleaseEvidence) -> ReleaseProjection:
    """Project already-verified physical facts; never stop, delete, transfer or persist."""
    if current.identity != evidence.identity or current.allocation_revision != evidence.expected_allocation_revision:
        raise ValueError("release_identity_or_revision_mismatch")
    if (evidence.closure == "unknown" or evidence.closure_evidence_ref is None
            or current.pending_resource_adjustment_id is not None):
        return ReleaseProjection(remaining_accounted_vector=current.accounted_vector,
                                 effective_hard_limits=current.hard_limits)
    remaining = current.accounted_vector.disk_bytes
    if evidence.disk_remaining_bytes is not None:
        if evidence.disk_evidence_ref is None or evidence.disk_remaining_bytes > remaining:
            raise ValueError("disk_remaining_bytes_need_bounded_physical_evidence")
        remaining = evidence.disk_remaining_bytes
    transfer = evidence.retention_transfer
    if transfer is not None:
        if (transfer.identity != current.identity or transfer.allocation_revision != current.allocation_revision
                or evidence.disk_remaining_bytes is None or evidence.disk_evidence_ref is None
                or transfer.retained_bytes != remaining):
            raise ValueError("disk_transfer_must_preserve_all_remaining_bytes_and_identity")
        remaining = 0
    return ReleaseProjection(remaining_accounted_vector=ResourceVector(disk_bytes=remaining),
                             effective_hard_limits=ResourceVector(),
                             transferred_retained_bytes=transfer.retained_bytes if transfer else 0)


class P0ResourceContracts(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    pool: HostResourcePool
    request: ResourceRequest
    allocation: ResourceAllocation
    adjustment: ResourceAdjustment
    pending_adjustment: PendingAdjustmentAccounting
    release_evidence: ResourceReleaseEvidence
    release_projection: ReleaseProjection
    retention_transfer: DiskRetentionTransfer
