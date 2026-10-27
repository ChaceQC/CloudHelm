"""Project Task-owned resource execution barriers from the execution ledger."""

from sqlalchemy import select

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.fact_reads import bounded_rows
from modules.collaboration.operation_projection import merge_operation_facts
from modules.execution.tables import resource_reservations, resource_runners
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.resource_contracts import ResourceAllocation, ResourceVector
from packages.contracts.p0.task_control_contracts import OperationClosureFact
from packages.contracts.p1.resource_protocol import (
    DEVELOPMENT_BACKEND, STORAGE_BACKEND, ExecutorReceipt, ReserveResourcesRequest,
    RunnerRegistration, allocation_from_receipt, match_runner,
)


def _shared_backing(connection, row, request, allocation, receipt, runner):
    """A confirmed disk-only backing owner can be referenced by other Tasks."""
    if (request.backend != STORAGE_BACKEND or allocation.state != "active"
            or receipt.state != "running" or runner.storage is None
            or receipt.process_binding != "storage-" + runner.storage.storage_id
            or receipt.evidence.get("whole_backing_charged") is not True
            or receipt.evidence.get("backing_bytes") != request.resources.hard_limits.disk_bytes
            or allocation.accounted_vector != request.resources.accounted_vector
            or allocation.hard_limits != request.resources.hard_limits):
        return False
    registrations = bounded_rows(connection, select(resource_runners).where(
        resource_runners.c.host_resource_pool_id == row["host_resource_pool_id"],
        resource_runners.c.registration_json["storage_owner_reservation_id"].astext == row["reservation_id"],
    ), "resource_operation_scope_too_large")
    for record in registrations:
        try:
            other = RunnerRegistration.model_validate(record["registration_json"])
        except ValueError:
            continue
        if (other.backend == DEVELOPMENT_BACKEND and other.executor_instance_id == record["executor_instance_id"]
                and other.host_resource_pool_id == record["host_resource_pool_id"]
                and other.storage == runner.storage and other.hub_incarnation == runner.hub_incarnation
                and other.resource_generation == runner.resource_generation):
            return True
    return False


def _execution_closed(connection, row):
    """Accept only a bound ledger/receipt projection; disk retention remains charged."""
    try:
        request = ReserveResourcesRequest.model_validate(row["request_json"])
        allocation = ResourceAllocation.model_validate(row["allocation_json"])
        runner = RunnerRegistration.model_validate(row["runner_json"])
        receipt = ExecutorReceipt.model_validate(row["receipt_json"])
        identity = request.resources.identity
        if (identity != allocation.identity or receipt.identity != identity
                or identity.reservation_id != row["reservation_id"]
                or identity.operation_id != row["operation_id"]
                or identity.host_resource_pool_id != row["host_resource_pool_id"]
                or identity.executor_instance_id != row["executor_instance_id"]
                or request.resources.request_digest != allocation.creation_request_digest
                or receipt.request_digest != allocation.creation_request_digest
                or receipt.sequence == 0 or receipt.sequence != row["receipt_sequence"]
                or allocation.pending_resource_adjustment_id is not None):
            return False
        match_runner(runner, request.resources, request.backend)
        if allocation_from_receipt(allocation, receipt) != allocation:
            return False
        if allocation.state in {"releasing", "released"} and receipt.state in {"closed_unstarted", "stopped"}:
            return (allocation.hard_limits == ResourceVector()
                    and allocation.accounted_vector == ResourceVector(disk_bytes=allocation.accounted_vector.disk_bytes))
        return _shared_backing(connection, row, request, allocation, receipt, runner)
    except TaskBoundaryError:
        raise
    except ValueError:
        # Invalid, missing or contradictory ledger facts never prove physical closure.
        return False


def merge_resource_operation_blockers(connection, task_id, operations):
    """Preserve existing facts and add/strengthen only unsettled Task-owned executions."""
    rows = bounded_rows(connection, select(
        resource_reservations, resource_runners.c.registration_json.label("runner_json"),
    ).outerjoin(resource_runners, resource_runners.c.executor_instance_id == resource_reservations.c.executor_instance_id)
        .where(resource_reservations.c.task_id == task_id).order_by(resource_reservations.c.operation_id),
        "resource_operation_scope_too_large")
    by_id = {fact.operation_ref.object_id: fact for fact in operations}
    added = []
    for row in rows:
        if _execution_closed(connection, row):
            continue
        identity = row["operation_id"]
        existing = by_id.get(identity)
        if existing is not None:
            by_id[identity] = existing.model_copy(update={
                "owner_kind": "task", "owner_id": task_id, "affects_completion": True,
                "closure": "unknown", "closure_evidence_ref": None, "effects_recorded": False,
            })
        else:
            added.append(OperationClosureFact(
                operation_ref=EngineeringRef(kind="operation", object_id=identity,
                                             revision="p1-resources-r1", authority="execution"),
                owner_kind="task", owner_id=task_id, affects_completion=True, closure="unknown",
            ))
    return merge_operation_facts(tuple(by_id[fact.operation_ref.object_id] for fact in operations), added)
