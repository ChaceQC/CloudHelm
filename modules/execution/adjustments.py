"""Persist r1's explicit no-adjustment result without ever changing physical limits."""

from sqlalchemy import insert, select

from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from packages.contracts.p0.resource_contracts import ResourceAdjustment, ResourceAllocation, validate_new_adjustment
from packages.contracts.p1.resource_protocol import ResourceAdjustmentResult, adjustment_digest
from .application import read_reservation
from .registry import lock_pool
from .tables import resource_adjustments


def adjust(application, actor, reservation_id, request):
    request = ResourceAdjustment.model_validate(request.model_dump(mode="python"))
    if request.request_digest != adjustment_digest(request):
        raise ValueError("resource_adjustment_digest_mismatch")
    if request.identity.reservation_id != reservation_id:
        raise ValueError("resource_adjustment_reservation_mismatch")
    with UnitOfWork(application.control_engine) as uow:
        assert_schema_ready(uow.connection)
        row = read_reservation(uow, reservation_id)
        lock_task_access(uow, actor, row["task_id"], "operation.request")
        lock_pool(uow, row["host_resource_pool_id"])
        # A global transaction lock serializes reuse of an adjustment ID across
        # pools as well as retries in one pool. It never covers executor I/O.
        uow.connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                      ("resource-adjustment:" + request.resource_adjustment_id,))
        previous = uow.connection.execute(select(resource_adjustments).where(
            resource_adjustments.c.resource_adjustment_id == request.resource_adjustment_id,
        )).mappings().one_or_none()
        if previous is not None:
            if previous["request_json"] != request.model_dump(mode="json"):
                raise ValueError("resource_adjustment_identity_digest_conflict")
            return ResourceAdjustmentResult.model_validate(previous["result_json"])
        current = ResourceAllocation.model_validate(read_reservation(uow, reservation_id)["allocation_json"])
        status, code = "unchanged", "resource_limits_unchanged"
        try:
            validate_new_adjustment(current, request)
        except ValueError as error:
            status, code = "rejected", str(error)
        result = ResourceAdjustmentResult(resource_adjustment_id=request.resource_adjustment_id,
            request_digest=request.request_digest, status=status, code=code, allocation=current)
        uow.connection.execute(insert(resource_adjustments).values(
            resource_adjustment_id=request.resource_adjustment_id, reservation_id=reservation_id,
            request_digest=request.request_digest, request_json=request.model_dump(mode="json"),
            result_json=result.model_dump(mode="json")))
        return result
