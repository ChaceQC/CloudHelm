"""Task-owned admission, immutable operation bindings and shared backing ownership."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.collaboration.guards import read_task
from modules.execution.application import ResourceApplication, read_reservation
from modules.execution.dispatch import ResourceDispatcher
from modules.execution.registry import read_runner
from modules.execution.tables import resource_reservations
from modules.identity.actors import actor_for_command
from packages.contracts.p0.resource_contracts import AllocationIdentity, ResourceAllocation, ResourceRequest, ResourceVector
from packages.contracts.p1.resource_protocol import (
    DEVELOPMENT_BACKEND, STORAGE_BACKEND, ReserveResourcesRequest, canonical_digest, resource_request_digest,
)

runner_module = "services.dev-runner."


class EngineeringResources:
    def __init__(self, engine, control_engine, registry):
        self.application = ResourceApplication(engine, control_engine)
        self.registry = registry
        self.registry.endpoint_context = self.storage_context

    @contextmanager
    def admitted(self):
        try:
            storage = self.registry.current_storage()
        except Exception as error:
            if str(error) != "engineering_storage_admission_required":
                raise
            with self.registry.admit(0) as storage:
                yield storage
        else:
            yield storage

    def _configuration(self):
        registration = self.registry.registration
        if registration is None or registration.resource_runner_id is None:
            raise ValueError("engineering_shared_resources_not_configured")
        with UnitOfWork(self.application.control_engine) as uow:
            process = read_runner(uow, registration.resource_runner_id)
            storage = read_runner(uow, registration.storage_runner_id)
        if (process.backend != DEVELOPMENT_BACKEND or storage.backend != STORAGE_BACKEND
                or process.storage != registration.storage or storage.storage != registration.storage
                or process.host_resource_pool_id != storage.host_resource_pool_id
                or process.storage_owner_reservation_id != registration.storage_owner_reservation_id):
            raise ValueError("engineering_resource_registration_mismatch")
        return process, storage

    def _existing(self, reservation_id):
        with UnitOfWork(self.application.control_engine) as uow:
            row = uow.connection.execute(select(resource_reservations).where(
                resource_reservations.c.reservation_id == reservation_id,
            )).mappings().one_or_none()
            if row is None:
                return None
            return ReserveResourcesRequest.model_validate(row["request_json"]), ResourceAllocation.model_validate(row["allocation_json"])

    def _dispatcher(self, registration):
        channel = import_module(runner_module + "resource_channel").ResourceChannel(registration)
        return ResourceDispatcher(self.application, channel)

    def _reserve(self, registration, reservation_id, task_id, command_id, operation_id, vector, deadline, conflicts):
        existing = self._existing(reservation_id)
        if existing is not None:
            request, allocation = existing
            if (request.resources.identity.executor_instance_id != registration.executor_instance_id
                    or request.resources.identity.resource_group_digest != registration.recipe_digest):
                raise ValueError("engineering_resource_existing_binding_mismatch")
            return request, allocation
        with UnitOfWork(self.application.control_engine) as uow:
            actor = actor_for_command(uow, command_id)
            task = read_task(uow.connection, task_id)
        identity = AllocationIdentity(reservation_id=reservation_id, operation_id=operation_id,
            resource_group_id=reservation_id, resource_group_digest=registration.recipe_digest,
            host_resource_pool_id=registration.host_resource_pool_id,
            executor_instance_id=registration.executor_instance_id, hub_incarnation=registration.hub_incarnation,
            resource_generation=registration.resource_generation, cpu_period_us=registration.cpu_period_us,
            conflict_keys=tuple(sorted(conflicts)))
        resource = ResourceRequest(identity=identity, request_digest="sha256:" + "0" * 64,
                                   request_vector=vector, accounted_vector=vector, hard_limits=vector)
        resource = ResourceRequest.model_validate(resource.model_dump() | {"request_digest": resource_request_digest(resource)})
        request = ReserveResourcesRequest(protocol_revision="p1-resources-r2", expected_version=task["version"],
            expected_control_revision=task["control_revision"], expected_input_validity_revision=task["input_validity_revision"],
            expires_at_utc=deadline, resources=resource, backend=registration.backend)
        try:
            result = self.application.reserve(actor, task_id, request, idempotency_key=reservation_id)
        except Exception:
            # Another Task may have acquired the same permanent backing owner.
            existing = self._existing(reservation_id)
            if existing is None or existing[0].resources.identity.executor_instance_id != registration.executor_instance_id:
                raise
            return existing
        return request, result.allocation

    def _storage_owner(self, registration, process, storage, task_id, command_id, deadline):
        identity = registration.storage_owner_reservation_id
        vector = ResourceVector(disk_bytes=storage.admission.snapshot.accounted_backing_bytes)
        request, allocation = self._reserve(process, identity, task_id, command_id, identity, vector, deadline, ())
        dispatcher = self._dispatcher(process)
        if allocation.state == "reserved":
            dispatcher.deliver(identity)
            allocation = dispatcher.start(identity)
        else:
            allocation = dispatcher.reconcile(identity)
        if allocation.accounted_vector.disk_bytes != vector.disk_bytes or allocation.state not in {"active", "releasing"}:
            raise ValueError("engineering_backing_ownership_unconfirmed")

    def binding(self, *, key, task_id, command_id, deadline, storage, start):
        process, backing = self._configuration()
        identity = "engineering-resource-" + canonical_digest({"key": key, "storage": process.storage.model_dump(mode="json")})[7:47]
        existing = self._existing(identity)
        if existing is None and not start:
            return None  # Only queries/stops use this legacy compatibility route.
        if existing is None:
            self._storage_owner(self.registry.registration, backing, storage, task_id, command_id, deadline)
        envelope = import_module(runner_module + "resource_development").ENVELOPE
        request, allocation = self._reserve(process, identity, task_id, command_id, identity, envelope, deadline,
            ("engineering-storage-" + process.storage.storage_id,))
        dispatcher = self._dispatcher(process)
        if start:
            if allocation.state == "reserved":
                dispatcher.deliver(identity)
                allocation = dispatcher.start(identity)
            else:
                allocation = dispatcher.reconcile(identity)
            if allocation.state != "active":
                raise ValueError("engineering_resource_start_unconfirmed")
        context = import_module(runner_module + "resource_context")
        return context.BoundGroup(request, process, dispatcher, stopped=allocation.state == "released")

    def environment(self, access, storage, *, start=False):
        if self.registry.registration.resource_runner_id is None:
            if start:
                raise ValueError("engineering_shared_resources_not_configured")
            return None
        environment = access.environment
        return self.binding(key="environment:" + environment["environment_id"],
            task_id=environment["task_id"], command_id=environment["created_by_command_id"],
            deadline=environment["created_at"] + timedelta(hours=2), storage=storage, start=start)

    @contextmanager
    def build(self, record, storage, gate):
        journal = storage.archive_root / "build-operations" / record.command_id / "intent.json"
        new = not journal.exists()
        if not new and self.registry.registration.resource_runner_id is None:
            yield None
            return
        if new:
            gate()
        binding = self.binding(key=record.operation_id, task_id=record.task_id, command_id=record.command_id,
            deadline=record.accepted_at + timedelta(hours=2), storage=storage, start=new)
        if binding is None:
            yield None
        else:
            with binding.context():
                yield binding

    @contextmanager
    def storage_context(self):
        registration = self.registry.registration
        if registration is None or registration.resource_runner_id is None:
            yield
            return
        with UnitOfWork(self.application.control_engine) as uow:
            rows = uow.connection.execute(select(resource_reservations).where(
                resource_reservations.c.executor_instance_id == registration.resource_runner_id,
            )).mappings().all()
        live = [row for row in rows if ResourceAllocation.model_validate(row["allocation_json"]).state
                not in {"released", "releasing"}]
        if len(live) > 1:
            raise ValueError("engineering_multiple_live_resource_bindings")
        if not live:
            yield
            return
        row = live[0]
        request = ReserveResourcesRequest.model_validate(row["request_json"])
        process, _ = self._configuration()
        context = import_module(runner_module + "resource_context")
        with context.BoundGroup(request, process, self._dispatcher(process)).context():
            yield
