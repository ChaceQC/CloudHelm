"""Application-owned transactions and a fresh start gate for trusted dispatchers."""

from sqlalchemy import func, select

from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.identity.actors import actor_for_command
from packages.contracts.p0.resource_contracts import ResourceAdjustment, ResourceAllocation
from packages.contracts.p1.resource_protocol import ReserveResourcesRequest, match_runner
from .commands import reserve_in_uow
from .errors import ResourceError
from .registry import lock_pool, read_runner
from .preview_admission import require_resource_progress
from .tables import resource_reservations


def read_reservation(uow, reservation_id):
    row = uow.connection.execute(select(resource_reservations).where(
        resource_reservations.c.reservation_id == reservation_id,
    )).mappings().one_or_none()
    if row is None:
        raise ValueError("resource_reservation_not_found")
    return row


class ResourceApplication:
    def __init__(self, engine, control_engine):
        self.engine, self.control_engine = engine, control_engine

    def adjust(self, actor, reservation_id, request: ResourceAdjustment):
        from .adjustments import adjust

        try:
            return adjust(self, actor, reservation_id, request)
        except ValueError as error:
            if type(error) is not ValueError:
                raise
            raise ResourceError(str(error)) from None

    def reserve(self, actor, task_id, request: ReserveResourcesRequest, *, idempotency_key):
        try:
            with UnitOfWork(self.engine) as uow:
                return reserve_in_uow(uow, actor, task_id, request, idempotency_key=idempotency_key)
        except ValueError as error:
            if type(error) is not ValueError:
                raise
            raise ResourceError(str(error)) from None

    def query(self, actor, reservation_id):
        try:
            with UnitOfWork(self.control_engine) as uow:
                row = read_reservation(uow, reservation_id)
                lock_task_access(uow, actor, row["task_id"], "resource.read")
                return ResourceAllocation.model_validate(row["allocation_json"])
        except ValueError as error:
            if type(error) is not ValueError:
                raise
            raise ResourceError(str(error)) from None

    def check_start(self, reservation_id):
        """Called under the executor's host lock immediately before physical start.

        This is a current authorization/expiry check, not a remote deployment
        permit or a cross-machine transaction. No caller-supplied approval flag.
        """
        with UnitOfWork(self.control_engine) as uow:
            assert_schema_ready(uow.connection)
            row = read_reservation(uow, reservation_id)
            actor = actor_for_command(uow, row["command_id"])
            task, _ = lock_task_access(uow, actor, row["task_id"], "operation.request")
            request = ReserveResourcesRequest.model_validate(row["request_json"])
            require_resource_progress(uow, actor, task, request, at_start=True)
            registration = lock_pool(uow, row["host_resource_pool_id"])
            allocation = ResourceAllocation.model_validate(read_reservation(uow, reservation_id)["allocation_json"])
            identity = allocation.identity
            if (allocation.state not in {"reserved", "active"}
                    or identity.hub_incarnation != registration.hub_incarnation
                    or identity.resource_generation != registration.resource_generation
                    or request.expires_at_utc <= uow.connection.scalar(select(func.clock_timestamp()))):
                raise ValueError("resource_start_gate_closed")
            match_runner(read_runner(uow, row["executor_instance_id"]), request.resources, request.backend)
