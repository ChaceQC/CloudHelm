"""One-time preview-slot maintenance for an existing shared host registration."""

import fcntl
import os
import sqlite3
from pathlib import Path

from sqlalchemy import select, update

from database.readiness import require_maintenance_role
from database.uow import UnitOfWork
from modules.execution.tables import resource_pools, resource_reservations, resource_runners
from packages.contracts.p0.resource_contracts import ResourceAllocation, ResourceRequest, ResourceVector, vector_sum
from packages.contracts.p1.resource_protocol import (
    DEVELOPMENT_BACKEND, ExecutorReceipt, ReserveResourcesRequest, allocation_from_receipt,
)

from . import resource_ledger
from .preview_network import _proxy_cgroup
from .resource_development import PREVIEW_ENVELOPE, development_recipe
from .resource_storage import observe_backing


def _registrations(original, target):
    before = {entry.runner.executor_instance_id: entry for entry in original.registrations}
    after = {entry.runner.executor_instance_id: entry for entry in target.registrations}
    if (len(before) != len(original.registrations) or len(after) != len(target.registrations)
            or before.keys() != after.keys() or not target.preview_proxy_cgroup
            or original.preview_proxy_cgroup not in (None, target.preview_proxy_cgroup)):
        raise ValueError("resource_preview_registration_identity_mismatch")
    old_pool = next(iter(before.values())).pool
    new_pool = next(iter(after.values())).pool
    developers = [key for key, entry in before.items() if entry.runner.backend == DEVELOPMENT_BACKEND]
    if (len(developers) != 1 or any(entry.pool != old_pool for entry in before.values())
            or any(entry.pool != new_pool for entry in after.values())
            or old_pool.pool.physical_host_id != resource_ledger.observed_host_id()
            or set(before) != set(old_pool.pool.executor_instance_ids)):
        raise ValueError("resource_preview_existing_host_mismatch")
    developer = developers[0]
    expected = old_pool.model_dump(mode="json")
    base, changed = expected["pool"], new_pool.pool
    if (base["configured_budget"]["preview_slots"] != 0 or base["measured_allocatable_capacity"] is None
            or base["measured_allocatable_capacity"]["preview_slots"] != 0
            or base["unknown_occupancy_upper_bound"] is None
            or base["unknown_occupancy_upper_bound"]["preview_slots"] != 0
            or not changed.capacity_evidence_ref or changed.capacity_evidence_ref == base["capacity_evidence_ref"]):
        raise ValueError("resource_preview_capacity_evidence_required")
    base["configured_budget"]["preview_slots"] = 1
    base["measured_allocatable_capacity"]["preview_slots"] = 1
    base["capacity_revision"] += 1
    base["capacity_evidence_ref"] = changed.capacity_evidence_ref
    if expected != new_pool.model_dump(mode="json"):
        raise ValueError("resource_preview_pool_change_invalid")
    for key, entry in before.items():
        runner = entry.runner.model_dump(mode="json")
        updated = after[key].runner
        if key == developer:
            if (runner["maximum"]["preview_slots"] != 0 or not updated.capability_evidence_ref
                    or updated.capability_evidence_ref == runner["capability_evidence_ref"]):
                raise ValueError("resource_preview_capability_evidence_required")
            runner["maximum"]["preview_slots"] = 1
            runner["capability_evidence_ref"] = updated.capability_evidence_ref
        if runner != updated.model_dump(mode="json") or entry.argv != after[key].argv:
            raise ValueError("resource_preview_runner_change_invalid")
    return before, after, old_pool, new_pool, developer


def _local_allocations(db):
    allocations = {}
    for raw_request, raw_receipt in db.execute("SELECT request_json, receipt_json FROM allocations"):
        request = ResourceRequest.model_validate_json(raw_request)
        receipt = ExecutorReceipt.model_validate_json(raw_receipt)
        initial = ResourceAllocation(identity=request.identity, creation_request_digest=request.request_digest,
            allocation_revision=1, state="reserved", accounted_vector=request.accounted_vector,
            hard_limits=request.hard_limits)
        projected = allocation_from_receipt(initial, receipt)
        if projected.accounted_vector != ResourceVector():
            allocations[request.identity.reservation_id] = (request, projected)
    return allocations


def _check_occupancy(connection, pool, local):
    rows = connection.execute(select(resource_reservations).where(
        resource_reservations.c.host_resource_pool_id == pool.pool.host_resource_pool_id)).mappings().all()
    hub = {}
    for row in rows:
        allocation = ResourceAllocation.model_validate(row["allocation_json"])
        if allocation.accounted_vector != ResourceVector():
            hub[row["reservation_id"]] = (ReserveResourcesRequest.model_validate(row["request_json"]).resources, allocation)
    if hub.keys() != local.keys():
        raise ValueError("resource_preview_occupancy_reconciliation_required")
    for key, (request, allocation) in local.items():
        recorded_request, recorded = hub[key]
        if (request != recorded_request or allocation.identity != recorded.identity
                or allocation.accounted_vector != recorded.accounted_vector
                or allocation.hard_limits != recorded.hard_limits or allocation.state != recorded.state
                or recorded.pending_resource_adjustment_id is not None):
            raise ValueError("resource_preview_occupancy_reconciliation_required")
    charged = vector_sum(tuple(allocation.accounted_vector for _, allocation in local.values()))
    if any(getattr(charged, name) for name in ("memory_mib", "cpu_millicores", "pids", "heavy_slots", "preview_slots")):
        raise ValueError("resource_preview_active_processes_require_stop")
    total = vector_sum((charged, pool.pool.unknown_occupancy_upper_bound, PREVIEW_ENVELOPE))
    for name in ResourceVector.model_fields:
        if getattr(total, name) > min(getattr(pool.pool.configured_budget, name),
                                      getattr(pool.pool.measured_allocatable_capacity, name)):
            raise ValueError("resource_preview_shared_capacity_insufficient")


def _check_physical(registration, proxy_cgroup):
    _proxy_cgroup(proxy_cgroup)
    reference = registration.storage
    if (development_recipe(reference, registration.storage_owner_reservation_id) != registration.recipe_digest
            or registration.cpu_period_us != 100000
            or any(getattr(PREVIEW_ENVELOPE, name) > getattr(registration.maximum, name)
                   for name in ResourceVector.model_fields)):
        raise ValueError("resource_preview_runner_capability_mismatch")
    if not observe_backing(reference, mounted=True).managed_docker:
        raise ValueError("resource_preview_managed_storage_required")
    memory = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
                  if line.startswith("MemAvailable:"))
    data = Path("/home/cloudhelm/.local/state/cloudhelm/development-storage") / reference.storage_id / "data"
    filesystem = os.statvfs(data)
    if (memory < (PREVIEW_ENVELOPE.memory_mib + 128) * 1024
            or len(os.sched_getaffinity(0)) * 1000 < PREVIEW_ENVELOPE.cpu_millicores
            or filesystem.f_bavail * filesystem.f_frsize < PREVIEW_ENVELOPE.disk_bytes):
        raise ValueError("resource_preview_physical_headroom_insufficient")


def enable_preview_slot(engine, original, target):
    if os.geteuid() != 0:
        raise ValueError("resource_host_explicit_root_maintenance_required")
    before, after, old_pool, new_pool, developer = _registrations(original, target)
    directory = resource_ledger.ROOT / old_pool.pool.physical_host_id
    resource_ledger._private_directory(directory)
    descriptor = resource_ledger._file(directory / "start.lock")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with sqlite3.connect((directory / "ledger.sqlite3").as_uri() + "?mode=rw", uri=True,
                             isolation_level=None, timeout=5) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            values = dict(db.execute("SELECT key, value FROM configuration"))
            from packages.contracts.p1.resource_protocol import PoolRegistration, RunnerRegistration

            local_pool = PoolRegistration.model_validate_json(values["pool"])
            local_runners = {key: RunnerRegistration.model_validate_json(values["runner:" + key]) for key in before}
            local_old = local_pool == old_pool and all(local_runners[k] == before[k].runner for k in before)
            local_new = local_pool == new_pool and all(local_runners[k] == after[k].runner for k in after)
            if not (local_old or local_new):
                raise ValueError("resource_preview_local_registration_mismatch")
            local = _local_allocations(db)
            with UnitOfWork(engine) as uow:
                connection = uow.connection
                require_maintenance_role(connection)
                row = connection.execute(select(resource_pools).where(
                    resource_pools.c.host_resource_pool_id == old_pool.pool.host_resource_pool_id).with_for_update()).mappings().one()
                runners = connection.execute(select(resource_runners).where(
                    resource_runners.c.host_resource_pool_id == old_pool.pool.host_resource_pool_id).with_for_update()).mappings().all()
                hub_pool = PoolRegistration.model_validate(row["registration_json"])
                hub_runners = {row["executor_instance_id"]: RunnerRegistration.model_validate(row["registration_json"])
                               for row in runners}
                hub_old = hub_pool == old_pool and hub_runners == {k: v.runner for k, v in before.items()}
                hub_new = hub_pool == new_pool and hub_runners == {k: v.runner for k, v in after.items()}
                if not (hub_old or hub_new):
                    raise ValueError("resource_preview_hub_registration_mismatch")
                if local_new and hub_new:
                    db.execute("COMMIT")
                    return "already_registered"
                _check_occupancy(connection, new_pool, local)
                _check_physical(after[developer].runner, target.preview_proxy_cgroup)
                if local_old:
                    db.execute("UPDATE configuration SET value=? WHERE key='pool'", (new_pool.model_dump_json(),))
                    db.execute("UPDATE configuration SET value=? WHERE key=?",
                               (after[developer].runner.model_dump_json(), "runner:" + developer))
                if hub_old:
                    connection.execute(update(resource_pools).where(
                        resource_pools.c.host_resource_pool_id == old_pool.pool.host_resource_pool_id).values(
                            registration_json=new_pool.model_dump(mode="json")))
                    connection.execute(update(resource_runners).where(
                        resource_runners.c.executor_instance_id == developer).values(
                            registration_json=after[developer].runner.model_dump(mode="json")))
                # The executor commits first; an interrupted Hub commit is resumed with these same inputs.
                db.execute("COMMIT")
        return "registered"
    finally:
        os.close(descriptor)
