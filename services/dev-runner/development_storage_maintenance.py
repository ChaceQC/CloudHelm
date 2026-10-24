"""Explicit maintenance of this project's bounded local regular-file instances."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import development_storage as storage
from .development_storage_pin import assert_no_container_mounts, backing_pin
from packages.contracts.p1.development_storage import (
    MAX_STORAGE_BYTES, MIN_STORAGE_BYTES, DevelopmentStorageRef, DevelopmentStorageRegistration,
)

DEVELOPMENT_PURPOSES = ("git", "workspace", "candidate", "cache", "archive")
HOST_SAFETY_BYTES = 1024**3


def command(arguments: list[str], *descriptors: int) -> None:
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
            env={"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            pass_fds=descriptors, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        raise storage.DevelopmentStorageError("storage_maintenance_command_timeout") from None
    if result.returncode:
        raise storage.DevelopmentStorageError("storage_maintenance_command_rejected")


def mount(instance: int, storage_id: str) -> dict:
    image = storage.regular_at(instance, "volume.ext4", flags=os.O_RDWR)
    target = storage.directory_at(instance, "data")
    try:
        if os.fstat(target).st_dev != os.fstat(instance).st_dev or os.listdir(target):
            raise storage.DevelopmentStorageError("storage_target_not_empty_unmounted_directory")
        command(["/usr/bin/mount", "-i", "-n", "--no-canonicalize", "-t", "ext4", "-o",
                 "loop,nodev,nosuid,noexec,nodiscard", f"/proc/self/fd/{image}",
                 f"/proc/self/fd/{instance}/data"], image, instance)
    finally:
        os.close(image)
        os.close(target)
    data = os.open("data", storage.DIRECTORY_FLAGS, dir_fd=instance)
    try:
        os.fchown(data, storage.UID, storage.UID)
        os.fchmod(data, 0o700)
        registration = storage.registration_at(instance, storage_id)
        for purpose in registration.allowed_purposes:
            child = storage.directory_at(data, storage.PURPOSE_DIRECTORIES[purpose], create=True)
            os.close(child)
        os.fsync(data)
        return storage.mounted_identity(data, storage_id)
    finally:
        os.close(data)


def unmount(instance: int, storage_id: str) -> dict:
    data = storage.directory_at(instance, "data")
    try:
        if os.fstat(data).st_dev == os.fstat(instance).st_dev:
            if os.listdir(data):
                raise storage.DevelopmentStorageError("storage_unmounted_target_not_empty")
            expected = str(storage.ROOT / storage_id / "volume.ext4")
            for path in Path("/sys/block").glob("loop*/loop/backing_file"):
                if path.read_text(encoding="utf-8").strip() == expected:
                    raise storage.DevelopmentStorageError("storage_backing_still_attached")
            return {"already_unmounted": True, "backing_not_attached": True}
        identity = storage.mounted_identity(data, storage_id)
    finally:
        os.close(data)
    # No mounted-root fd remains open; no lazy or forced unmount is permitted.
    command(["/usr/bin/umount", "-i", "-n", "--no-canonicalize",
             f"/proc/self/fd/{instance}/data"], instance)
    data = storage.directory_at(instance, "data")
    try:
        if os.fstat(data).st_dev != os.fstat(instance).st_dev or os.listdir(data):
            raise storage.DevelopmentStorageError("storage_unmount_not_confirmed")
    finally:
        os.close(data)
    backing = storage.ROOT / storage_id / "volume.ext4"
    sysfs = Path("/sys/dev/block") / identity["mount_device"] / "loop/backing_file"
    if sysfs.exists() and sysfs.read_text(encoding="utf-8").strip() == str(backing):
        raise storage.DevelopmentStorageError("storage_loop_detach_not_confirmed")
    return identity


def evidence(root: int, storage_id: str, phase: str, value: dict) -> dict:
    reports = storage.directory_at(root, "evidence", create=True)
    try:
        payload = {"storage_id": storage_id, "phase": phase,
                   "observed_at": datetime.now(timezone.utc).isoformat(), **value}
        storage.save_json(reports, storage_id + "." + phase + ".json", payload)
        return payload
    finally:
        os.close(reports)


def create_instance(capacity_bytes: int, *, fixture: bool = False, purposes=DEVELOPMENT_PURPOSES,
                    managed_docker: bool = False) -> dict:
    if os.getuid() != 0:
        raise storage.DevelopmentStorageError("storage_explicit_root_maintenance_required")
    if (type(capacity_bytes) is not int or not MIN_STORAGE_BYTES <= capacity_bytes <= MAX_STORAGE_BYTES
            or capacity_bytes % 1024**2 or (fixture and capacity_bytes != storage.FIXTURE_BYTES)
            or not purposes or len(set(purposes)) != len(purposes)
            or not set(purposes).issubset(DEVELOPMENT_PURPOSES)):
        raise storage.DevelopmentStorageError("storage_maintenance_capacity_or_purpose_invalid")
    storage_id = "dev-storage-" + uuid.uuid4().hex
    root = storage.root_descriptor(create=True)
    instance = None
    try:
        host = os.fstatvfs(root)
        if capacity_bytes + HOST_SAFETY_BYTES > host.f_bavail * host.f_frsize:
            raise storage.DevelopmentStorageError("storage_host_capacity_or_safety_unavailable")
        os.mkdir(storage_id, 0o700, dir_fd=root)
        os.chown(storage_id, storage.UID, storage.UID, dir_fd=root, follow_symlinks=False)
        instance = storage.directory_at(root, storage_id)
        target = storage.directory_at(instance, "data", create=True)
        os.close(target)
        lock = storage.regular_at(instance, "admission.lock", flags=os.O_RDWR, create=True)
        os.close(lock)
        image = storage.regular_at(instance, "volume.ext4", flags=os.O_RDWR, create=True)
        filesystem_uuid = str(uuid.uuid4())
        try:
            os.posix_fallocate(image, 0, capacity_bytes)
            command(["/usr/sbin/mkfs.ext4", "-q", "-F", "-m", "0", "-U", filesystem_uuid,
                     "-E", "nodiscard,lazy_itable_init=0,lazy_journal_init=0", f"/proc/self/fd/{image}"], image)
            os.fsync(image)
            state = os.fstat(image)
            registration = DevelopmentStorageRegistration(storage_id=storage_id,
                method_revision="p1-development-storage-r3" if managed_docker else "p1-development-storage-r2",
                managed_docker=managed_docker,
                instance_revision=uuid.uuid4().hex, filesystem_uuid=filesystem_uuid,
                backing_file_bytes=capacity_bytes, backing_device=state.st_dev,
                backing_inode=state.st_ino, created_at=datetime.now(timezone.utc),
                scope="local_development_fixture_only" if fixture else "local_controlled_development",
                allowed_purposes=("fixture",) if fixture else purposes)
            storage.save_json(instance, "registration.json", registration.model_dump(mode="json"))
        finally:
            os.close(image)
        with storage.instance_lock(instance):
            identity = mount(instance, storage_id)
        return evidence(root, storage_id, "create", {
            "registration": registration.model_dump(mode="json"), "mount": identity,
            "references": {purpose: DevelopmentStorageRef(storage_id=storage_id,
                instance_revision=registration.instance_revision, purpose=purpose).model_dump(mode="json")
                for purpose in registration.allowed_purposes},
            "maintenance_mount_namespace": os.readlink("/proc/self/ns/mnt"),
            "pid1_mount_namespace": os.readlink("/proc/1/ns/mnt"),
            "backing_file_bytes": state.st_size, "backing_allocated_bytes": state.st_blocks * 512})
    finally:
        if instance is not None:
            os.close(instance)
        os.close(root)


def create_fixture() -> dict:
    return create_instance(storage.FIXTURE_BYTES, fixture=True)


def _unmount_for_maintenance(instance, storage_id):
    with backing_pin(instance, exclusive=True):
        registration = storage.registration_at(instance, storage_id)
        assert_no_container_mounts(storage_id)
        previous = unmount(instance, storage_id)
    # Close the backing fd before deletion and byte reclamation measurement.
    # The caller still holds the short admission lock on the unmounted pool.
    return registration, previous


def change_fixture(storage_id: str, action: str) -> dict:
    if os.getuid() != 0 or action not in ("unmount", "remount", "remove"):
        raise storage.DevelopmentStorageError("storage_explicit_root_maintenance_required")
    with storage.instance_descriptors(storage_id) as (root, instance), storage.instance_lock(instance):
        registration, previous = _unmount_for_maintenance(instance, storage_id)
        if action == "unmount":
            return evidence(root, storage_id, "unmount", {"unmounted": previous, "loop_detached": True,
                "accounted_backing_bytes": registration.backing_file_bytes, "backing_file_retained": True})
        if action == "remount":
            current = mount(instance, storage_id)
            return evidence(root, storage_id, "remount", {
                "instance_revision": registration.instance_revision,
                "unmounted": previous, "mounted": current, "same_backing_file": True})
        if set(os.listdir(instance)) != {"data", "volume.ext4", "registration.json", "admission.lock"}:
            raise storage.DevelopmentStorageError("storage_cleanup_unknown_instance_entries")
        before = os.fstatvfs(root)
        for name in ("volume.ext4", "registration.json", "admission.lock"):
            descriptor = storage.regular_at(instance, name)
            os.close(descriptor)
            os.unlink(name, dir_fd=instance)
        os.rmdir("data", dir_fd=instance)
        current = os.stat(storage_id, dir_fd=root, follow_symlinks=False)
        opened = os.fstat(instance)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise storage.DevelopmentStorageError("storage_cleanup_instance_replaced")
        os.rmdir(storage_id, dir_fd=root)
        os.fsync(root)
        # Large ext4 files may finish releasing extents after directory fsync.
        # Flush this filesystem before observing free blocks; never infer release
        # solely from an unlinked path or a detached loop device.
        command(["/usr/bin/sync", "-f", f"/proc/self/fd/{root}"], root)
        after = os.fstatvfs(root)
        reclaimed = max(0, (after.f_bfree - before.f_bfree) * after.f_frsize)
        confirmed = reclaimed >= registration.backing_file_bytes
        return evidence(root, storage_id, "cleanup", {
            "unmounted": previous, "loop_detached": True, "backing_file_deleted": True,
            "instance_directory_deleted": True, "host_free_byte_increase": reclaimed,
            "host_free_bytes_before": before.f_bfree * before.f_frsize,
            "host_free_bytes_after": after.f_bfree * after.f_frsize,
            "host_reclamation_confirmed": confirmed,
            "reclaimed_backing_file_bytes": registration.backing_file_bytes if confirmed else 0,
            "remaining_accounted_bytes": 0 if confirmed else registration.backing_file_bytes})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create-fixture", "verify-fixture", "create-pool", "verify-pool",
                                           "unmount", "remount", "remove"))
    parser.add_argument("storage_id", nargs="?")
    parser.add_argument("--capacity-bytes", type=int)
    parser.add_argument("--purpose", choices=DEVELOPMENT_PURPOSES, action="append")
    parser.add_argument("--observe-cross-call", action="store_true")
    parser.add_argument("--managed-docker", action="store_true")
    args = parser.parse_args()
    create_actions = ("create-fixture", "verify-fixture", "create-pool", "verify-pool")
    if (os.getuid() != 0 or (args.action not in create_actions and not args.storage_id)
            or (args.action in create_actions and args.storage_id)):
        raise storage.DevelopmentStorageError("storage_explicit_root_maintenance_required")
    if ((args.capacity_bytes is not None or args.purpose or args.managed_docker) and args.action != "create-pool"):
        raise storage.DevelopmentStorageError("storage_maintenance_option_not_applicable")
    if args.observe_cross_call and args.action != "verify-fixture":
        raise storage.DevelopmentStorageError("storage_maintenance_option_not_applicable")
    if args.action == "verify-fixture":
        return verify_fixture(args.observe_cross_call)
    if args.action == "verify-pool":
        return verify_fixture(controlled_pool=True)
    if args.action == "create-pool":
        if args.capacity_bytes is None:
            raise storage.DevelopmentStorageError("storage_explicit_capacity_required")
        result = create_instance(args.capacity_bytes, purposes=tuple(args.purpose or DEVELOPMENT_PURPOSES),
                                 managed_docker=args.managed_docker)
    else:
        result = create_fixture() if args.action == "create-fixture" else change_fixture(args.storage_id, args.action)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


def verify_fixture(observe_cross_call: bool = False, *, controlled_pool: bool = False) -> int:
    """Keep maintenance and unprivileged checks in the same explicit namespace."""
    created = create_instance(64 * 1024**2) if controlled_pool else create_fixture()
    storage_id = created["storage_id"]
    cleaned = False
    try:
        if observe_cross_call:
            print(json.dumps({"stage": "fixture_ready_for_readonly_cross_call_observation",
                              "storage_id": storage_id, "created": created}), flush=True)
            time.sleep(8)
        for phase in ("fill", "unmounted", "retained", "cleanup-proof"):
            if phase == "unmounted":
                change_fixture(storage_id, "unmount")
            if phase == "retained":
                change_fixture(storage_id, "remount")
            if phase == "cleanup-proof":
                change_fixture(storage_id, "remove")
                cleaned = True
            result = subprocess.run([sys.executable, "-m", "scripts.p1.probe_development_storage", phase, storage_id],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                user=storage.UID, group=storage.UID, extra_groups=(), timeout=30, check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
            payload = json.loads(result.stdout)
            if result.returncode:
                raise storage.DevelopmentStorageError(payload.get("failure", "storage_fixture_probe_failed"))
        print(json.dumps({"storage_id": storage_id, "all_required_verified": True,
            "report_path": payload["report_path"], "report_digest": payload["report_digest"], "fixture_removed": True,
            "provider_capacity_bytes": created["registration"]["backing_file_bytes"],
            "scope": "local_registered_provider_only" if controlled_pool else "32MiB_local_fixture_only",
            "application_writers_verified": False, "large_development_pool_created": False}), flush=True)
        return 0
    finally:
        if not cleaned:
            change_fixture(storage_id, "remove")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as failure:
        category = str(failure) if isinstance(failure, storage.DevelopmentStorageError) else type(failure).__name__
        print(json.dumps({"verified": False, "failure": category}), flush=True)
        raise SystemExit(1) from None
