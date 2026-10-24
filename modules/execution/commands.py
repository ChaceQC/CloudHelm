"""Whole-group admission in the caller's short UoW; no executor I/O here."""

from uuid import uuid4

from sqlalchemy import func, insert, select

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import require_transaction
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.guards import require_ordinary_progress, task_resource
from modules.sync.events import append_event
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p0.resource_contracts import ResourceAllocation, validate_admission
from packages.contracts.p1.resource_protocol import (
    PROTOCOL, STORAGE_BACKEND, ReservationResult, ReserveResourcesRequest, match_runner,
)
from .registry import lock_pool, read_runner
from .tables import resource_reservations


def reserve_in_uow(uow, actor, task_id, request: ReserveResourcesRequest, *, idempotency_key):
    require_transaction(uow.connection)
    # Savepoint keeps all domain/command/event writes atomic even if the caller
    # catches a rejection and commits unrelated work in the outer transaction.
    with uow.connection.begin_nested():
        return _reserve(uow, actor, task_id, request, idempotency_key)


def _reserve(uow, actor, task_id, request, key):
    request = ReserveResourcesRequest.model_validate(request.model_dump(mode="python"))
    assert_schema_ready(uow.connection)
    task, authorization = lock_task_access(uow, actor, task_id, "operation.request")
    resource = task_resource(task)
    intent = CommandIntent(
        request_schema_revision=PROTOCOL, caller=actor.principal, scope=resource.scope,
        target=resource.target_scope, action="operation.request",
        expected_resource_revision=request.expected_version,
    )
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                               idempotency_key=key, request_digest=request_digest(intent, request))
    previous = lock_and_get(uow.connection, envelope)
    if previous is not None:
        return ReservationResult.model_validate(previous.result)
    require_ordinary_progress(
        uow.connection, task_id, expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision,
        allowed_states=("draft", "active"),
    )
    now = uow.connection.scalar(select(func.clock_timestamp()))
    if request.expires_at_utc <= now:
        raise ValueError("resource_request_expired")
    allocation = _reserve_group(uow, task_id, envelope.command_id, request)
    result = ReservationResult(command_id=envelope.command_id, task_id=task_id, allocation=allocation)
    save_result(uow.connection, envelope, result, status_code=202, authorization=authorization.envelope)
    append_event(uow.connection, command_id=envelope.command_id, project_id=task["project_id"],
                 aggregate_kind="resource_reservation", aggregate_id=allocation.identity.reservation_id,
                 aggregate_version=1, event_type="resource.reserved", schema_version=PROTOCOL, payload=result)
    return result


def _reserve_group(uow, task_id, command_id, request):
    resources = request.resources
    identity = resources.identity
    registration = lock_pool(uow, identity.host_resource_pool_id)
    if (identity.hub_incarnation != registration.hub_incarnation
            or identity.resource_generation != registration.resource_generation):
        raise ValueError("resource_control_generation_mismatch")
    runner = read_runner(uow, identity.executor_instance_id)
    match_runner(runner, resources, request.backend)
    rows = uow.connection.execute(select(resource_reservations).where(
        resource_reservations.c.host_resource_pool_id == identity.host_resource_pool_id,
    )).mappings().all()
    allocations = tuple(ResourceAllocation.model_validate(row["allocation_json"]) for row in rows)
    if runner.backend == STORAGE_BACKEND:
        for row, current in zip(rows, allocations):
            previous = read_runner(uow, row["executor_instance_id"])
            if (current.accounted_vector.disk_bytes and previous.backend == STORAGE_BACKEND
                    and previous.storage == runner.storage):
                raise ValueError("resource_storage_backing_already_owned")
    if any(row["operation_id"] == identity.operation_id for row in rows):
        raise ValueError("resource_operation_identity_already_reserved")
    if any(a.identity.resource_group_id == identity.resource_group_id and a.state != "released"
           for a in allocations):
        raise ValueError("resource_group_already_reserved")
    validate_admission(registration.pool, allocations, resources)
    allocation = ResourceAllocation(identity=identity, creation_request_digest=resources.request_digest,
        allocation_revision=1, state="reserved", accounted_vector=resources.accounted_vector,
        hard_limits=resources.hard_limits)
    uow.connection.execute(insert(resource_reservations).values(
        reservation_id=identity.reservation_id, host_resource_pool_id=identity.host_resource_pool_id,
        executor_instance_id=identity.executor_instance_id, operation_id=identity.operation_id,
        task_id=task_id, command_id=command_id, request_json=request.model_dump(mode="json"),
        allocation_json=allocation.model_dump(mode="json"),
    ))
    return allocation
