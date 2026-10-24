"""One permanent charge for a fixed, fully allocated development backing file."""

import os

from packages.contracts.p0.resource_contracts import ResourceAllocation, ResourceRequest
from packages.contracts.p1.resource_protocol import (
    STORAGE_BACKEND, ExecutorReceipt, RunnerRegistration, allocation_from_receipt, canonical_digest,
)
from . import development_storage as storage
from .development_storage_pin import assert_no_container_mounts, backing_pin


def storage_recipe(reference):
    return canonical_digest({"backend": STORAGE_BACKEND, "storage": reference.model_dump(mode="json")})


def observe_backing(reference, *, mounted=False):
    with storage.instance_descriptors(reference.storage_id) as (_, instance):
        registration = storage.registration_at(instance, reference.storage_id)
        if registration.instance_revision != reference.instance_revision:
            raise ValueError("resource_storage_revision_mismatch")
        image = storage.regular_at(instance, "volume.ext4")
        try:
            actual = os.fstat(image)
            if ((actual.st_dev, actual.st_ino, actual.st_size) !=
                    (registration.backing_device, registration.backing_inode, registration.backing_file_bytes)
                    or actual.st_blocks * 512 < registration.backing_file_bytes):
                raise ValueError("resource_storage_backing_not_fully_allocated")
        finally:
            os.close(image)
        if mounted:
            data = storage.directory_at(instance, "data")
            try:
                if os.fstat(data).st_dev == os.fstat(instance).st_dev:
                    raise ValueError("resource_storage_registered_mount_required")
                storage.mounted_identity(data, reference.storage_id)
            finally:
                os.close(data)
        return registration


class StorageBoundary:
    backend = STORAGE_BACKEND

    def __init__(self, registration):
        self.registration = registration
        if storage_recipe(registration.storage) != registration.recipe_digest:
            raise ValueError("resource_storage_recipe_mismatch")

    def binding(self, request):
        return "storage-" + self.registration.storage.storage_id

    def check_capability(self, request):
        registration = observe_backing(self.registration.storage)
        if (request.identity.resource_group_digest != self.registration.recipe_digest
                or request.hard_limits.disk_bytes != registration.backing_file_bytes):
            raise ValueError("resource_storage_requires_whole_backing_charge")
        with self.ledger.locked() as db:
            for raw, fact in db.execute("SELECT request_json, receipt_json FROM allocations"):
                old = ResourceRequest.model_validate_json(raw)
                if old.identity.reservation_id == request.identity.reservation_id:
                    continue
                configuration = db.execute("SELECT value FROM configuration WHERE key=?",
                    ("runner:" + old.identity.executor_instance_id,)).fetchone()
                previous = RunnerRegistration.model_validate_json(configuration[0])
                if previous.backend != STORAGE_BACKEND or previous.storage != self.registration.storage:
                    continue
                current = ResourceAllocation(identity=old.identity, creation_request_digest=old.request_digest,
                    allocation_revision=1, state="reserved", accounted_vector=old.accounted_vector, hard_limits=old.hard_limits)
                if allocation_from_receipt(current, ExecutorReceipt.model_validate_json(fact)).accounted_vector.disk_bytes:
                    raise ValueError("resource_storage_backing_already_owned")

    def start(self, request):
        self.check_capability(request)
        return {"whole_backing_charged": True, "backing_bytes": request.hard_limits.disk_bytes}

    def observe(self, request):
        self.check_capability(request)
        return "running", False, {"whole_backing_charged": True, "backing_bytes": request.hard_limits.disk_bytes}

    def stop(self, request):
        # Ending execution does not delete the backing or relinquish byte ownership.
        with storage.instance_descriptors(self.registration.storage.storage_id) as (_, instance):
            with backing_pin(instance, exclusive=True):
                assert_no_container_mounts(self.registration.storage.storage_id)
                self.check_capability(request)
        return False, {"whole_backing_retained": True, "disk_remaining_bytes": request.hard_limits.disk_bytes}

    def observe_stopped(self, request):
        self.check_capability(request)
        return "stopped", False, {"whole_backing_retained": True,
                                   "disk_remaining_bytes": request.hard_limits.disk_bytes}
