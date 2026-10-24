"""Maintenance-only immutable pool/Runner registration; never trusts client flags."""

from sqlalchemy import insert, select, text

from database.readiness import require_maintenance_role
from database.uow import require_transaction
from packages.contracts.p1.resource_protocol import PoolRegistration, RunnerRegistration
from .tables import resource_pools, resource_runners


def register_pool_in_uow(uow, registration: PoolRegistration):
    require_transaction(uow.connection)
    require_maintenance_role(uow.connection)
    uow.connection.execute(text("SELECT pg_advisory_xact_lock(73913001)"))
    pool = registration.pool
    row = uow.connection.execute(select(resource_pools).where(
        (resource_pools.c.host_resource_pool_id == pool.host_resource_pool_id)
        | (resource_pools.c.physical_host_id == pool.physical_host_id),
    ).with_for_update()).mappings().one_or_none()
    payload = registration.model_dump(mode="json")
    if row is not None:
        if row["registration_json"] != payload:
            raise ValueError("physical_host_pool_already_registered")
        return
    if (pool.measured_allocatable_capacity is None or pool.unknown_occupancy_upper_bound is None
            or not all((pool.host_identity_evidence_ref, pool.capacity_evidence_ref, pool.group_limits_evidence_ref))):
        raise ValueError("resource_pool_evidence_required")
    uow.connection.execute(insert(resource_pools).values(
        host_resource_pool_id=pool.host_resource_pool_id, physical_host_id=pool.physical_host_id,
        registration_json=payload,
    ))


def register_runner_in_uow(uow, registration: RunnerRegistration):
    require_maintenance_role(uow.connection)
    pool = lock_pool(uow, registration.host_resource_pool_id)
    if (registration.physical_host_id != pool.pool.physical_host_id
            or registration.executor_instance_id not in pool.pool.executor_instance_ids
            or registration.hub_incarnation != pool.hub_incarnation
            or registration.resource_generation != pool.resource_generation):
        raise ValueError("runner_host_pool_binding_mismatch")
    existing = uow.connection.execute(select(resource_runners.c.registration_json).where(
        resource_runners.c.executor_instance_id == registration.executor_instance_id,
    )).scalar_one_or_none()
    payload = registration.model_dump(mode="json")
    if existing is not None:
        if existing != payload:
            raise ValueError("runner_registration_conflict")
        return
    uow.connection.execute(insert(resource_runners).values(
        executor_instance_id=registration.executor_instance_id,
        host_resource_pool_id=registration.host_resource_pool_id, registration_json=payload,
    ))


def lock_pool(uow, pool_id):
    require_transaction(uow.connection)
    row = uow.connection.execute(select(resource_pools.c.registration_json).where(
        resource_pools.c.host_resource_pool_id == pool_id,
    ).with_for_update()).scalar_one_or_none()
    if row is None:
        raise ValueError("resource_pool_not_registered")
    return PoolRegistration.model_validate(row)


def read_runner(uow, executor_id):
    row = uow.connection.execute(select(resource_runners.c.registration_json).where(
        resource_runners.c.executor_instance_id == executor_id,
    )).scalar_one_or_none()
    if row is None:
        raise ValueError("resource_runner_not_registered")
    return RunnerRegistration.model_validate(row)
