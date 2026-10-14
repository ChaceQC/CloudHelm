"""Fixed P0 resource shape/arithmetic cases; no physical capacity or ledger evidence."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.p0.resource_contracts import (
    AllocationIdentity, DiskRetentionTransfer, HostResourcePool, PendingAdjustmentAccounting,
    ResourceAdjustment, ResourceAllocation, ResourceLimits, ResourceReleaseEvidence,
    ResourceRequest, ResourceVector, project_release, validate_admission, validate_new_adjustment,
)

GIB = 1024 ** 3
DIGEST = "sha256:" + "a" * 64  # Shape-only fixture; not an attested request digest.


def _rejected(action: Callable[[], object], reason: str) -> None:
    try:
        action()
    except ValueError as error:
        if reason in str(error):
            return
        raise AssertionError(f"unexpected rejection; expected {reason}") from error
    raise AssertionError(f"missing rejection: {reason}")


def _identity(name: str, runner: str = "runner-a", conflicts: tuple[str, ...] = ()) -> AllocationIdentity:
    return AllocationIdentity(reservation_id=name, operation_id=f"operation-{name}",
                              resource_group_id=f"group-{name}", resource_group_digest=DIGEST,
                              host_resource_pool_id="fixture-host-pool", executor_instance_id=runner,
                              hub_incarnation="fixture-incarnation", resource_generation=1,
                              cpu_period_us=100000, conflict_keys=conflicts)


def _request(name: str, vector: ResourceVector, runner: str = "runner-a") -> ResourceRequest:
    return ResourceRequest(identity=_identity(name, runner), request_digest=DIGEST,
                           request_vector=vector, accounted_vector=vector, hard_limits=vector)


def _pool() -> HostResourcePool:
    capacity = ResourceVector(memory_mib=4096, cpu_millicores=3000, disk_bytes=8 * GIB,
                              pids=256, heavy_slots=1, preview_slots=1)
    return HostResourcePool(host_resource_pool_id="fixture-host-pool", physical_host_id="fixture-host",
                            executor_instance_ids=("runner-a", "runner-b"), capacity_revision=1,
                            configured_budget=capacity, measured_allocatable_capacity=capacity,
                            unknown_occupancy_upper_bound=ResourceVector(),
                            host_identity_evidence_ref="synthetic-host-reference",
                            capacity_evidence_ref="synthetic-capacity-reference",
                            group_limits_evidence_ref="synthetic-limits-reference")


def _current() -> ResourceAllocation:
    vector = ResourceVector(memory_mib=2048, cpu_millicores=2000, disk_bytes=8 * GIB,
                            pids=128, heavy_slots=1)
    return ResourceAllocation(identity=_identity("current"), creation_request_digest=DIGEST,
                              allocation_revision=4, state="active",
                              accounted_vector=vector, hard_limits=vector)


def _admission_checks() -> dict[str, bool]:
    pool = _pool()
    four_gib = _request("four-gib", ResourceVector(memory_mib=4096))
    validate_admission(pool, (), four_gib)
    _rejected(lambda: ResourceRequest(identity=four_gib.identity, request_digest=DIGEST,
                                      request_vector=four_gib.request_vector,
                                      accounted_vector=four_gib.accounted_vector,
                                      hard_limits=ResourceVector(memory_mib=5120)),
              "hard_limits_exceed_accounted_vector")
    lower_capacity = HostResourcePool(**{**pool.model_dump(), "measured_allocatable_capacity":
                                        ResourceVector(memory_mib=3072)})
    _rejected(lambda: validate_admission(lower_capacity, (), four_gib), "shared_host_capacity_exceeded")
    unbounded = HostResourcePool(**{**pool.model_dump(), "unknown_occupancy_upper_bound": None})
    _rejected(lambda: validate_admission(unbounded, (), four_gib), "resource_environment_or_unknown_occupancy_unverified")
    outstanding = tuple(ResourceAllocation(identity=_identity(state, "runner-b"),
                                           creation_request_digest=DIGEST, allocation_revision=0, state=state,
                                           accounted_vector=ResourceVector(memory_mib=1024),
                                           hard_limits=ResourceVector(memory_mib=1024))
                        for state in ("reserved", "active", "releasing", "orphaned"))
    _rejected(lambda: validate_admission(pool, outstanding, _request("extra", ResourceVector(memory_mib=1))),
              "shared_host_capacity_exceeded")
    _rejected(lambda: ResourceVector(memory_mib=True), "int_type")
    _rejected(lambda: setattr(four_gib.accounted_vector, "memory_mib", 1), "frozen_instance")
    return {"4gib_valid_vector_admitted": True, "4gib_accounted_5gib_hard_limit_rejected": True,
            "measured_total_caps_budget": True, "unknown_upper_bound_required": True,
            "all_four_outstanding_states_count_across_runners": True, "strict_frozen_vectors": True}


def _adjustment_checks() -> dict[str, bool]:
    current = _current()
    target = ResourceVector(memory_mib=3072, cpu_millicores=1000, disk_bytes=6 * GIB,
                            pids=64, heavy_slots=1)
    adjustment = ResourceAdjustment(resource_adjustment_id="adjust-1", request_digest=DIGEST,
                                    identity=current.identity, expected_allocation_revision=4,
                                    target=ResourceLimits(accounted_vector=target, hard_limits=target))
    held = ResourceVector(memory_mib=3072, cpu_millicores=2000, disk_bytes=8 * GIB,
                          pids=128, heavy_slots=1)
    pending = PendingAdjustmentAccounting(adjustment=adjustment, state="unknown", allocation_revision=4,
                                          previous_accounted_vector=current.accounted_vector, accounted_vector=held)
    held_allocation = ResourceAllocation(**{**current.model_dump(), "accounted_vector": held,
                                            "pending_resource_adjustment_id": "adjust-1"})
    extra = _request("during-unknown", ResourceVector(memory_mib=2048))
    _rejected(lambda: validate_admission(_pool(), (held_allocation,), extra, pending_adjustments=(pending,)),
              "shared_host_capacity_exceeded")
    undercounted = ResourceAllocation(**{**held_allocation.model_dump(), "accounted_vector": current.accounted_vector})
    _rejected(lambda: validate_admission(_pool(), (undercounted,), extra, pending_adjustments=(pending,)),
              "pending_adjustment_snapshot_does_not_match_allocation")
    _rejected(lambda: PendingAdjustmentAccounting(**{**pending.model_dump(),
                                                     "accounted_vector": current.accounted_vector}),
              "pending_adjustment_requires_dimensionwise_maximum")
    _rejected(lambda: PendingAdjustmentAccounting(**{**pending.model_dump(), "allocation_revision": 5}),
              "pending_adjustment_cannot_advance_confirmed_revision")
    _rejected(lambda: validate_new_adjustment(current, adjustment), "in_place_resource_adjustment_unsupported")
    stale = ResourceAdjustment(**{**adjustment.model_dump(), "expected_allocation_revision": 3})
    _rejected(lambda: validate_new_adjustment(current, stale), "allocation_revision_conflict")
    occupied = ResourceAllocation(**{**current.model_dump(), "pending_resource_adjustment_id": "older-adjustment"})
    _rejected(lambda: validate_new_adjustment(occupied, adjustment), "resource_adjustment_already_pending")
    unchanged = ResourceAdjustment(**{**adjustment.model_dump(), "target":
                                      ResourceLimits(accounted_vector=current.accounted_vector,
                                                     hard_limits=current.hard_limits)})
    validate_new_adjustment(current, unchanged)
    return {"unknown_adjustment_keeps_dimensionwise_maximum": True, "pending_hold_bound_to_admission_snapshot": True,
            "unknown_revision_not_advanced": True,
            "in_place_adjustment_rejected": True, "stale_and_second_pending_adjustment_rejected": True,
            "unchanged_adjustment_needs_no_limit_change": True}


def _release_checks() -> dict[str, bool]:
    current = _current()
    unknown = ResourceReleaseEvidence(identity=current.identity, expected_allocation_revision=4,
                                      closure="unknown", disk_remaining_bytes=0,
                                      disk_evidence_ref="synthetic-gc-request-is-not-stop-proof")
    if project_release(current, unknown).remaining_accounted_vector != current.accounted_vector:
        raise AssertionError("unknown stop released resources")
    missing_closure = ResourceReleaseEvidence(**{**unknown.model_dump(), "closure": "closed_unstarted"})
    if project_release(current, missing_closure).remaining_accounted_vector != current.accounted_vector:
        raise AssertionError("unproved closed_unstarted released resources")
    stopped = ResourceReleaseEvidence(identity=current.identity, expected_allocation_revision=4,
                                      closure="group_stopped", closure_evidence_ref="synthetic-closed-group",
                                      disk_remaining_bytes=7 * GIB, disk_evidence_ref="synthetic-allocated-bytes")
    projection = project_release(current, stopped)
    if projection.remaining_accounted_vector != ResourceVector(disk_bytes=7 * GIB) or projection.effective_hard_limits != ResourceVector():
        raise AssertionError("stopped group must retain seven GiB and have no execution limits")
    residual = ResourceAllocation(**{**current.model_dump(), "state": "releasing",
                                      "accounted_vector": projection.remaining_accounted_vector,
                                      "hard_limits": projection.effective_hard_limits})
    extra = _request("new-disk", ResourceVector(disk_bytes=2 * GIB), "runner-b")
    _rejected(lambda: validate_admission(_pool(), (residual,), extra), "shared_host_capacity_exceeded")
    transfer = DiskRetentionTransfer(transfer_id="transfer-1", request_digest=DIGEST, identity=current.identity,
                                     allocation_revision=4, retained_object_id="synthetic-retained-set",
                                     retained_bytes=7 * GIB, retention_limit_bytes=7 * GIB,
                                     observed_at_utc="2026-10-14T00:00:00Z",
                                     transfer_evidence_ref="synthetic-atomic-transfer")
    transferred = project_release(current, ResourceReleaseEvidence(**{**stopped.model_dump(), "retention_transfer": transfer}))
    if transferred.remaining_accounted_vector != ResourceVector() or transferred.transferred_retained_bytes != 7 * GIB:
        raise AssertionError("transfer must conserve all seven GiB")
    validate_admission(_pool(), (), _request("fits-disk", ResourceVector(disk_bytes=GIB)), (transfer,))
    _rejected(lambda: validate_admission(_pool(), (), extra, (transfer,)), "shared_host_capacity_exceeded")
    _rejected(lambda: validate_admission(_pool(), (residual,), extra, (transfer,)),
              "full_disk_transfer_cannot_also_charge_source_allocation")
    return {"unknown_or_unproved_stop_keeps_full_charge": True,
            "stopped_group_still_charges_7gib": True, "7gib_transfer_still_blocks_reallocation": True,
            "retention_transfer_cannot_double_count_source": True}


def run_checks() -> dict[str, bool]:
    return {**_admission_checks(), **_adjustment_checks(), **_release_checks()}


if __name__ == "__main__":
    print(json.dumps({"check": "p0.3-resource-contracts", "scope": "types-and-pure-vector-arithmetic-only",
                      "checks": run_checks()}, ensure_ascii=False, sort_keys=True))
