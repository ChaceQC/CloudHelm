"""Shared host admission and physical release arithmetic only."""

from pydantic import ValidationError

from packages.contracts.p0.resource_contracts import (
    AllocationIdentity, HostResourcePool, PendingAdjustmentAccounting, ResourceAdjustment,
    ResourceAllocation, ResourceLimits, ResourceReleaseEvidence, ResourceRequest, ResourceVector,
    project_release, validate_admission, vector_max,
)

DIGEST = "sha256:" + "a" * 64
GIB = 1024 ** 3


def _reject(action, reason: str) -> None:
    try:
        action()
    except (ValueError, ValidationError) as error:
        if reason in str(error):
            return
        raise AssertionError(f"unexpected rejection: {reason}") from error
    raise AssertionError(f"missing rejection: {reason}")


def _identity(name: str) -> AllocationIdentity:
    return AllocationIdentity(
        reservation_id=name, operation_id=f"op-{name}", resource_group_id=f"group-{name}",
        resource_group_digest=DIGEST, host_resource_pool_id="host-pool", executor_instance_id="runner",
        hub_incarnation="hub", resource_generation=1, cpu_period_us=100000,
    )


def run_checks() -> dict[str, bool]:
    capacity = ResourceVector(memory_mib=4096)
    pool = HostResourcePool(
        host_resource_pool_id="host-pool", physical_host_id="host", executor_instance_ids=("runner",),
        capacity_revision=1, configured_budget=capacity, measured_allocatable_capacity=capacity,
        unknown_occupancy_upper_bound=ResourceVector(), host_identity_evidence_ref="host-fact",
        capacity_evidence_ref="capacity-fact", group_limits_evidence_ref="limits-fact",
    )
    request = ResourceRequest(
        identity=_identity("request"), request_digest=DIGEST,
        request_vector=capacity, accounted_vector=capacity, hard_limits=capacity,
    )
    validate_admission(pool, (), request)
    smaller = pool.model_copy(update={"measured_allocatable_capacity": ResourceVector(memory_mib=3072)})
    _reject(lambda: validate_admission(smaller, (), request), "shared_host_capacity_exceeded")

    allocation_vector = ResourceVector(memory_mib=2048, disk_bytes=8 * GIB)
    allocation = ResourceAllocation(
        identity=_identity("active"), creation_request_digest=DIGEST, allocation_revision=4,
        state="active", accounted_vector=allocation_vector, hard_limits=allocation_vector,
    )
    adjustment = ResourceAdjustment(
        resource_adjustment_id="adjustment", request_digest=DIGEST, identity=allocation.identity,
        expected_allocation_revision=4,
        target=ResourceLimits(accounted_vector=ResourceVector(memory_mib=3072),
                              hard_limits=ResourceVector(memory_mib=3072)),
    )
    held = vector_max(allocation_vector, adjustment.target.accounted_vector)
    PendingAdjustmentAccounting(
        adjustment=adjustment, previous_accounted_vector=allocation_vector, state="unknown",
        allocation_revision=4, accounted_vector=held,
    )
    _reject(lambda: PendingAdjustmentAccounting(
        adjustment=adjustment, previous_accounted_vector=allocation_vector, state="unknown",
        allocation_revision=4, accounted_vector=adjustment.target.accounted_vector,
    ), "pending_adjustment_requires_dimensionwise_maximum")
    unknown = ResourceReleaseEvidence(identity=allocation.identity, expected_allocation_revision=4, closure="unknown")
    assert project_release(allocation, unknown).remaining_accounted_vector == allocation_vector
    stopped = ResourceReleaseEvidence(
        identity=allocation.identity, expected_allocation_revision=4, closure="group_stopped",
        closure_evidence_ref="stopped-group", disk_remaining_bytes=7 * GIB, disk_evidence_ref="disk-fact",
    )
    assert project_release(allocation, stopped).remaining_accounted_vector == ResourceVector(
        disk_bytes=7 * GIB
    )
    return {"measured_host_capacity_caps_admission": True, "release_waits_for_stop_and_keeps_disk": True,
            "unknown_adjustment_uses_componentwise_maximum": True}
