"""Trusted post-commit Runner channel; receipts are queried, never publicly submitted."""

from sqlalchemy import update

from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.tables import tasks
from modules.sync.events import append_event
from packages.contracts.p0.resource_contracts import ResourceAllocation, ResourceVector
from packages.contracts.p1.resource_protocol import ExecutorReceipt, ReserveResourcesRequest
from .application import read_reservation
from .registry import lock_pool, read_runner
from .tables import resource_reservations


class ResourceDispatcher:
    def __init__(self, application, runner):
        self.application, self.runner = application, runner

    def _request(self, reservation_id):
        with UnitOfWork(self.application.control_engine) as uow:
            row = read_reservation(uow, reservation_id)
            registration = read_runner(uow, row["executor_instance_id"])
            if registration != self.runner.registration:
                raise ValueError("resource_executor_channel_binding_mismatch")
            return ReserveResourcesRequest.model_validate(row["request_json"])

    def deliver(self, reservation_id):
        request = self._request(reservation_id)
        self.runner.accept(request.resources, backend=request.backend)
        return self.reconcile(reservation_id)

    def start(self, reservation_id):
        self._request(reservation_id)
        self.runner.start(reservation_id, lambda: self.application.check_start(reservation_id))
        return self.reconcile(reservation_id)

    def stop(self, reservation_id):
        self._request(reservation_id)
        self._hold(reservation_id, "releasing")
        self.runner.stop(reservation_id)
        return self.reconcile(reservation_id)

    def reconcile(self, reservation_id):
        request = self._request(reservation_id)
        # Query is outside the Hub transaction. Transport failure retains all charge.
        try:
            receipt = self.runner.query(reservation_id)
        except (OSError, TimeoutError):
            return self._hold(reservation_id, "orphaned")
        if receipt is None:
            return self._hold(reservation_id, "orphaned")
        receipt = ExecutorReceipt.model_validate(receipt.model_dump(mode="python"))
        if receipt.identity != request.resources.identity or receipt.request_digest != request.resources.request_digest:
            raise ValueError("resource_receipt_identity_mismatch")
        with UnitOfWork(self.application.control_engine) as uow:
            assert_schema_ready(uow.connection)
            lock_pool(uow, receipt.identity.host_resource_pool_id)
            row = read_reservation(uow, reservation_id)
            current = ResourceAllocation.model_validate(row["allocation_json"])
            if receipt.sequence < row["receipt_sequence"]:
                return current
            if receipt.sequence == row["receipt_sequence"]:
                if receipt.sequence == row["receipt_sequence"] and row["receipt_json"] != receipt.model_dump(mode="json"):
                    raise ValueError("resource_receipt_sequence_conflict")
            terminal = receipt.state in {"closed_unstarted", "stopped"} and receipt.disk_reclaimed
            if current.state == "released" and not terminal:
                raise ValueError("resource_released_allocation_cannot_reopen")
            state = ("released" if terminal else "active" if receipt.state == "running" else
                     "reserved" if receipt.state == "accepted" else "orphaned")
            if receipt.sequence == row["receipt_sequence"] and current.state == state:
                return current
            values = {"state": state, "allocation_revision": current.allocation_revision + 1}
            if terminal:
                values |= {"accounted_vector": ResourceVector(), "hard_limits": ResourceVector()}
            changed = ResourceAllocation.model_validate(current.model_dump() | values)
            uow.connection.execute(update(resource_reservations).where(
                resource_reservations.c.reservation_id == reservation_id,
            ).values(allocation_json=changed.model_dump(mode="json"), receipt_json=receipt.model_dump(mode="json"),
                     receipt_sequence=receipt.sequence))
            _record_observation(uow, row, changed)
            return changed

    def _hold(self, reservation_id, state):
        with UnitOfWork(self.application.control_engine) as uow:
            row = read_reservation(uow, reservation_id)
            lock_pool(uow, row["host_resource_pool_id"])
            current = ResourceAllocation.model_validate(read_reservation(uow, reservation_id)["allocation_json"])
            if current.state == "released":
                return current
            changed = ResourceAllocation.model_validate(current.model_dump() | {
                "state": state, "allocation_revision": current.allocation_revision + 1,
            })
            uow.connection.execute(update(resource_reservations).where(
                resource_reservations.c.reservation_id == reservation_id,
            ).values(allocation_json=changed.model_dump(mode="json")))
            _record_observation(uow, row, changed)
            return changed


def _record_observation(uow, row, allocation):
    from sqlalchemy import select

    project_id = uow.connection.scalar(select(tasks.c.project_id).where(tasks.c.task_id == row["task_id"]))
    append_event(uow.connection, command_id=row["command_id"], project_id=project_id,
                 aggregate_kind="resource_reservation", aggregate_id=row["reservation_id"],
                 aggregate_version=allocation.allocation_revision, event_type="resource.observed",
                 schema_version="p1-resources-r1", payload=allocation)
