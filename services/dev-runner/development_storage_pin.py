"""Keep a registered pool mounted while independent, bounded dev writers live."""

import fcntl
import os
from contextlib import contextmanager

from . import development_storage as storage
from packages.contracts.p1.development_storage import DevelopmentStorageRef


@contextmanager
def backing_pin(instance, *, exclusive=False):
    descriptor = storage.regular_at(instance, "volume.ext4")
    try:
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise storage.DevelopmentStorageError("storage_lifetime_pin_busy") from None
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def pin_reference(owner, reference, requested_bytes):
    if (not isinstance(reference, DevelopmentStorageRef) or reference.storage_id != owner.storage_id
            or os.getuid() != storage.UID or type(requested_bytes) is not int or requested_bytes < 0
            or reference.purpose not in storage.PURPOSE_DIRECTORIES):
        raise storage.DevelopmentStorageError("storage_pin_request_invalid")
    with storage.instance_descriptors(owner.storage_id) as (_, instance), backing_pin(instance) as image:
        data = selected = None
        try:
            # Serialize admission checks, while the shared backing pin survives
            # this short critical section. The whole filesystem remains charged.
            with storage.instance_lock(instance):
                registration = storage.registration_at(instance, owner.storage_id)
                if registration.instance_revision != reference.instance_revision:
                    raise storage.DevelopmentStorageError("storage_instance_revision_stale")
                if (registration.scope != "local_controlled_development"
                        or reference.purpose not in registration.allowed_purposes):
                    raise storage.DevelopmentStorageError("storage_pin_scope_unsupported")
                data = storage.directory_at(instance, "data")
                snapshot = storage.observe_storage(instance, data, image, registration, reference.purpose)
                if requested_bytes > snapshot.allocatable_bytes:
                    raise storage.DevelopmentStorageError("storage_capacity_unavailable")
                name = storage.PURPOSE_DIRECTORIES[reference.purpose]
                selected = storage.directory_at(data, name)
                path = storage.ROOT / owner.storage_id / "data" / name
                if (os.fstat(selected).st_dev != os.fstat(data).st_dev
                        or os.readlink(f"/proc/self/fd/{selected}") != str(path)):
                    raise storage.DevelopmentStorageError("storage_purpose_path_replaced")
                admission = storage.StorageAdmission(selected, snapshot, path, instance, data, image)
            yield admission
            admission.observe()
        finally:
            if selected is not None:
                os.close(selected)
            if data is not None:
                os.close(data)


@contextmanager
def pin_admission(owner, admission):
    """Extend an already admitted pool without reacquiring its command lock."""
    if type(admission) is not storage.StorageAdmission or os.getuid() != storage.UID:
        raise storage.DevelopmentStorageError("storage_pin_admission_invalid")
    snapshot = admission.observe()
    if (snapshot.registration.storage_id != owner.storage_id
            or snapshot.registration.scope != "local_controlled_development"):
        raise storage.DevelopmentStorageError("storage_pin_scope_unsupported")
    descriptors = []
    try:
        for original in (admission.directory_fd, admission._instance_fd, admission._data_fd, admission._image_fd):
            descriptors.append(os.dup(original))
        selected, instance, data, image = descriptors
        try:
            fcntl.flock(image, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise storage.DevelopmentStorageError("storage_lifetime_pin_busy") from None
        lifetime = storage.StorageAdmission(selected, snapshot, admission.directory, instance, data, image)
        lifetime.observe()
        yield lifetime
        lifetime.observe()
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def assert_no_container_mounts(storage_id):
    # Reconciliation must still protect a pool after a host process loses its
    # pin. Inspect only mount/identity fields, never container Env or commands.
    from modules.workspaces.candidate_freeze import _inventory
    from modules.workspaces.candidate_writers import overlaps
    from modules.workspaces.safe_paths import WorkspaceFileError

    assert_no_managed_execution(storage_id)
    root = str(storage.ROOT / storage_id / "data")
    try:
        for container in _inventory():
            if any(mount.get("Source", "").startswith("/")
                   and overlaps(os.path.realpath(mount["Source"]), root)
                   for mount in container["mounts"]):
                raise storage.DevelopmentStorageError("storage_container_mounts_require_reconciliation")
    except WorkspaceFileError:
        raise storage.DevelopmentStorageError("storage_container_inventory_unavailable") from None


def assert_no_managed_execution(storage_id):
    """The durable fence survives loss of every Python reader pin and controller."""
    import json
    import sqlite3

    from packages.contracts.p1.resource_protocol import DEVELOPMENT_BACKEND, ExecutorReceipt, RunnerRegistration
    from .resource_ledger import ROOT

    for path in ROOT.glob("*/ledger.sqlite3"):
        try:
            with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as db:
                registrations = {key[7:]: RunnerRegistration.model_validate_json(value)
                    for key, value in db.execute("SELECT key, value FROM configuration WHERE key LIKE 'runner:%'")}
                for raw, fact in db.execute("SELECT request_json, receipt_json FROM allocations"):
                    request = json.loads(raw)
                    registration = registrations[request["identity"]["executor_instance_id"]]
                    receipt = ExecutorReceipt.model_validate_json(fact)
                    if (registration.backend == DEVELOPMENT_BACKEND and registration.storage.storage_id == storage_id
                            and not (receipt.state == "closed_unstarted" or receipt.state == "stopped" and receipt.disk_reclaimed)):
                        raise storage.DevelopmentStorageError("storage_managed_execution_requires_reconciliation")
        except (sqlite3.Error, ValueError, KeyError):
            raise storage.DevelopmentStorageError("storage_resource_ledger_unavailable") from None
