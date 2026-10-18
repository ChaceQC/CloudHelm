"""Focused pool lifetime checks used by the mutable environment method."""

from importlib import import_module
import os


def verify_storage_pin(reference):
    storage = import_module("services.dev-runner.development_storage")
    pins = import_module("services.dev-runner.development_storage_pin")
    owner = storage.DevelopmentStorage(reference.storage_id)
    with owner.pin_ref(reference) as lifetime:
        before = lifetime.observe()
        with owner.admit_ref(reference, requested_bytes=0) as command:
            after = command.observe()
            if ((os.fstat(command.directory_fd).st_dev, os.fstat(command.directory_fd).st_ino)
                    != (os.fstat(lifetime.directory_fd).st_dev, os.fstat(lifetime.directory_fd).st_ino)
                    or after.registration != before.registration):
                raise storage.DevelopmentStorageError("storage_pin_command_identity_mismatch")
        with storage.instance_descriptors(reference.storage_id) as (_, instance):
            try:
                with pins.backing_pin(instance, exclusive=True):
                    raise storage.DevelopmentStorageError("storage_pin_maintenance_was_admitted")
            except storage.DevelopmentStorageError as error:
                if str(error) != "storage_lifetime_pin_busy":
                    raise
        lifetime.observe()
    with storage.instance_descriptors(reference.storage_id) as (_, instance):
        with pins.backing_pin(instance, exclusive=True):
            pass
    return {"shared_pin_allows_serial_command": True,
            "maintenance_exclusive_pin_rejected_while_live": True,
            "maintenance_pin_available_after_close": True,
            "whole_backing_still_charged_bytes": before.accounted_backing_bytes}


def verify_container_recovery_guard(reference):
    storage = import_module("services.dev-runner.development_storage")
    pins = import_module("services.dev-runner.development_storage_pin")
    try:
        pins.assert_no_container_mounts(reference.storage_id)
    except storage.DevelopmentStorageError as error:
        if str(error) != "storage_container_mounts_require_reconciliation":
            raise
    else:
        raise storage.DevelopmentStorageError("storage_live_container_recovery_guard_missing")
    return {"physical_mount_inventory_blocks_reclamation_independently_of_pin": True}
