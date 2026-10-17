"""One local provider probe: fixed references, ENOSPC, retention and actual release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

from packages.contracts.p1.development_storage import DevelopmentStorageRef

storage = import_module("services.dev-runner.development_storage")
policy = import_module("services.dev-runner.policy")
PAYLOAD = b"CloudHelm dedicated persistent storage retained after writer exit\n" * 64
METHOD_FILES = ("packages/contracts/p1/development_storage.py",
    "services/dev-runner/development_storage.py", "services/dev-runner/development_storage_maintenance.py",
    "scripts/p1/probe_development_storage.py")
WRITER = '''import errno,json,os,sys
root=int(sys.argv[1]); ceiling=int(sys.argv[2]); count=0; exhausted=False
fd=os.open('overflow.bin',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=root)
try:
    while count <= ceiling:
        count += os.write(fd,b'x'*65536)
    os.fsync(fd)
except OSError as error:
    if error.errno != errno.ENOSPC: raise
    exhausted=True
finally:
    os.close(fd)
print(json.dumps({'enospc':exhausted,'written_bytes':count,'writer_stopped':True}),flush=True)
sys.exit(0 if exhausted else 1)
'''


def snapshot(reference: DevelopmentStorageRef):
    with storage.DevelopmentStorage(reference.storage_id).admit_ref(reference, requested_bytes=0) as admission:
        return admission.snapshot


def refusal(callback, expected: str) -> bool:
    try:
        with callback():
            pass
    except storage.DevelopmentStorageError as failure:
        if str(failure) == expected:
            return True
    raise storage.DevelopmentStorageError("storage_expected_refusal_missing")


def primary_reference(references: dict) -> DevelopmentStorageRef:
    return references.get("cache", references[next(iter(references))])


def write_retained_files(references: dict) -> dict:
    roots = {}
    for purpose, reference in references.items():
        with storage.DevelopmentStorage(reference.storage_id).admit_ref(reference, requested_bytes=1024**2) as admission:
            name = admission.directory.name
            if name not in {value["directory_name"] for value in roots.values()}:
                descriptor = storage.regular_at(admission.directory_fd, "retained.bin", flags=os.O_WRONLY, create=True)
                try:
                    os.write(descriptor, PAYLOAD)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            roots[purpose] = {"directory_name": name, "filesystem_device": os.fstat(admission.directory_fd).st_dev,
                             "accounted_backing_bytes": admission.snapshot.accounted_backing_bytes}
    if (len({item["filesystem_device"] for item in roots.values()}) != 1
            or ("candidate" in roots and roots["workspace"] != roots["candidate"])):
        raise storage.DevelopmentStorageError("storage_provider_roots_not_shared_as_registered")
    return roots


def fill(references: dict) -> dict:
    reference = primary_reference(references)
    target = storage.DevelopmentStorage(reference.storage_id)
    before = snapshot(reference)
    refused = refusal(lambda: target.admit_ref(reference,
        requested_bytes=before.allocatable_bytes + 1), "storage_capacity_unavailable")
    stale = refusal(lambda: target.admit_ref(reference.model_copy(update={"instance_revision": "0" * 32}),
        requested_bytes=0), "storage_instance_revision_stale")
    mismatch = refusal(lambda: target.admit_ref(reference.model_copy(update={"storage_id": "dev-storage-" + "0" * 32}),
        requested_bytes=0), "storage_reference_identity_mismatch")
    roots = write_retained_files(references)
    with target.admit_ref(reference, requested_bytes=1024**2) as admission:
        locked = refusal(lambda: target.admit_ref(next(iter(references.values())), requested_bytes=0),
                         "storage_admission_busy")
        result = subprocess.run([sys.executable, "-I", "-c", WRITER, str(admission.directory_fd),
            str(before.registration.backing_file_bytes)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", pass_fds=(admission.directory_fd,), timeout=20, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        if result.returncode:
            raise storage.DevelopmentStorageError("storage_enospc_writer_failed")
        writer = json.loads(result.stdout)
    after = snapshot(reference)
    if (not writer["enospc"] or after.retained_bytes_including_metadata <= before.retained_bytes_including_metadata
            or after.accounted_backing_bytes != before.accounted_backing_bytes or after.allocatable_bytes != 0):
        raise storage.DevelopmentStorageError("storage_enospc_or_retention_not_verified")
    return {"before": before.model_dump(mode="json"), "writer": writer,
            "after_writer_stopped": after.model_dump(mode="json"),
            "provider_roots": roots, "same_instance_lock_verified": locked,
            "oversized_admission_rejected": refused, "stale_instance_rejected": stale,
            "reference_identity_mismatch_rejected": mismatch,
            "request_is_free_space_gate_not_per_operation_quota": True,
            "retained_payload_digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest()}


def retained(references: dict) -> dict:
    for reference in references.values():
        with storage.DevelopmentStorage(reference.storage_id).admit_ref(reference, requested_bytes=0) as admission:
            descriptor = storage.regular_at(admission.directory_fd, "retained.bin")
            try:
                payload = os.read(descriptor, len(PAYLOAD) + 1)
            finally:
                os.close(descriptor)
            if payload != PAYLOAD or admission.snapshot.allocatable_bytes != 0:
                raise storage.DevelopmentStorageError("storage_remount_retained_read_mismatch")
    reference = primary_reference(references)
    with storage.DevelopmentStorage(reference.storage_id).admit_ref(reference, requested_bytes=0) as admission:
        before = admission.snapshot
        os.unlink("overflow.bin", dir_fd=admission.directory_fd)
        os.fsync(admission.directory_fd)
        after = admission.observe()
        reclaimed = after.filesystem_free_bytes - before.filesystem_free_bytes
        if reclaimed <= 0 or after.accounted_backing_bytes != before.accounted_backing_bytes:
            raise storage.DevelopmentStorageError("storage_file_release_not_physically_observed")
    return {"before_release": before.model_dump(mode="json"), "after_release": after.model_dump(mode="json"),
            "reclaimed_filesystem_bytes": reclaimed, "accounted_backing_bytes_unchanged": True,
            "retained_payload_digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest(),
            "read_after_remount_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("fill", "unmounted", "retained", "cleanup-proof"))
    parser.add_argument("storage_id")
    args = parser.parse_args()
    policy.acquire_probe_lock()
    storage.validate_id(args.storage_id)
    root = storage.root_descriptor()
    reports = storage.directory_at(root, "evidence")
    try:
        created = storage.read_json(reports, args.storage_id + ".create.json")
        references = {key: DevelopmentStorageRef.model_validate(value) for key, value in created["references"].items()}
        if args.phase == "fill":
            result = fill(references)
        elif args.phase == "unmounted":
            reference = primary_reference(references)
            result = {"unmounted_admission_rejected": refusal(
                lambda: storage.DevelopmentStorage(args.storage_id).admit_ref(reference, requested_bytes=0),
                "storage_dedicated_mount_missing"),
                "accounted_backing_bytes": created["registration"]["backing_file_bytes"]}
        elif args.phase == "retained":
            storage.read_json(reports, args.storage_id + ".remount.json")
            result = retained(references)
        else:
            entries = {phase: storage.read_json(reports, args.storage_id + "." + phase + ".json")
                       for phase in ("create", "fill", "unmount", "unmounted", "remount", "retained", "cleanup")}
            if args.storage_id in os.listdir(root):
                raise storage.DevelopmentStorageError("storage_cleanup_path_still_present")
            if not entries["cleanup"]["host_reclamation_confirmed"]:
                raise storage.DevelopmentStorageError("storage_host_reclamation_unconfirmed")
            reference = primary_reference(references)
            missing = refusal(lambda: storage.DevelopmentStorage(args.storage_id).admit_ref(reference, requested_bytes=0),
                              "storage_instance_unavailable")
            result = {"all_required_verified": True, "evidence": entries,
                      "removed_instance_rejected": missing, "fixture_removed": True,
                      "application_writers_verified": False, "large_development_pool_created": False}
        source_root = Path(__file__).resolve().parents[2]
        report = {"method_revision": storage.METHOD, "storage_id": args.storage_id,
            "phase": args.phase, "observed_at": datetime.now(timezone.utc).isoformat(),
            "environment": {"kernel": platform.release(), "uid": os.getuid(), "wsl_distribution": "Ubuntu-24.04"},
            "method_files": {name: "sha256:" + hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                             for name in METHOD_FILES}, "input_status": "development_worktree",
            "scope": "local_registered_provider_only",
            "provider_capacity_bytes": created["registration"]["backing_file_bytes"], **result}
        storage.save_json(reports, args.storage_id + "." + args.phase + ".json", report)
        report_path = storage.ROOT / "evidence" / (args.storage_id + "." + args.phase + ".json")
        print(json.dumps({"report_path": str(storage.ROOT / "evidence" / (
            args.storage_id + "." + args.phase + ".json")),
            "report_digest": "sha256:" + hashlib.sha256(report_path.read_bytes()).hexdigest(),
            **report}, ensure_ascii=False), flush=True)
        return 0
    finally:
        os.close(reports)
        os.close(root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as failure:
        category = (str(failure) if isinstance(failure, storage.DevelopmentStorageError)
                    else getattr(failure, "category", type(failure).__name__))
        print(json.dumps({"all_required_verified": False, "failure": category}), flush=True)
        raise SystemExit(1) from None
