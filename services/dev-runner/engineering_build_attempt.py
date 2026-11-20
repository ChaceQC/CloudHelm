"""Private acceptance, stop intent, and binding for the original build attempt."""

import fcntl
import json
import os
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from pydantic import model_validator

from modules.workspaces.safe_paths import exists_at, read_regular, write_new_file
from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p0.resource_contracts import AllocationIdentity
from packages.contracts.p1.build_records import BuildExecutionObservation, BuildRunRecord
from packages.contracts.p1.resource_protocol import DEVELOPMENT_BACKEND, ExecutorReceipt, canonical_digest, match_runner

from .toolchain import ProbeFailure

MAX_JOURNAL_BYTES = 1024**2


class BuildAttemptResource(Contract):
    identity: AllocationIdentity
    request_digest: Digest
    process_binding: Identifier


class BuildAttemptIntent(Contract):
    record: BuildRunRecord
    resource: BuildAttemptResource
    accepted_at: UtcTimestamp | None
    preaccept_stop_at: UtcTimestamp | None = None

    @model_validator(mode="after")
    def check_admission(self):
        if (self.accepted_at is None) == (self.preaccept_stop_at is None):
            raise ValueError("engineering_build_intent_admission_mismatch")
        return self


@dataclass(frozen=True)
class BuildAttemptInspection:
    accepted_at: datetime | None
    executor_instance_id: str
    executor_generation: int
    stop_requested_at: datetime | None
    observation: BuildExecutionObservation | None
    resource_receipt: ExecutorReceipt | None
    predecessor: BuildExecutionObservation | None


def read_attempt_intent(root_fd: int) -> BuildAttemptIntent | None:
    if not exists_at(root_fd, "intent.json"):
        return None
    value = json.loads(read_regular(root_fd, "intent.json", MAX_JOURNAL_BYTES))
    if "record" not in value:
        raise ProbeFailure("engineering_build_journal_requires_original_installation")
    return BuildAttemptIntent.model_validate(value)


def write_journal(root_fd: int, name: str, value) -> None:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_JOURNAL_BYTES:
        raise ProbeFailure("engineering_build_journal_bound_exceeded")
    if exists_at(root_fd, name):
        raise ProbeFailure("engineering_build_journal_identity_conflict")
    stage = "stage-" + uuid4().hex
    try:
        write_new_file(root_fd, stage, raw)
        os.rename(stage, name, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        if exists_at(root_fd, stage):
            os.unlink(stage, dir_fd=root_fd)


def try_lock_intent(root_fd: int) -> int | None:
    """Use the existing immutable journal inode to tell active submission from a lost worker."""
    descriptor = os.open("intent.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    return descriptor


def build_resource(storage, record: BuildRunRecord, group) -> BuildAttemptResource:
    if group is None:
        raise ProbeFailure("engineering_build_resource_binding_required")
    registration = group.registration
    storage_registration = storage.admission.snapshot.registration
    request = group.request
    resource = request.resources
    if (request.backend != DEVELOPMENT_BACKEND
            or registration.storage.storage_id != storage_registration.storage_id
            or registration.storage.instance_revision != storage_registration.instance_revision
            or group.dispatcher.runner.registration != registration):
        raise ProbeFailure("engineering_build_resource_binding_mismatch")
    match_runner(registration, resource, request.backend)
    reservation = "engineering-resource-" + canonical_digest({
        "key": record.operation_id, "storage": registration.storage.model_dump(mode="json"),
    })[7:47]
    if (resource.identity.reservation_id != reservation or resource.identity.resource_group_id != reservation
            or resource.identity.operation_id != record.operation_id):
        raise ProbeFailure("engineering_build_resource_binding_mismatch")
    return BuildAttemptResource(identity=resource.identity, request_digest=resource.request_digest,
                                process_binding=group.binding)


def query_resource(group, original: BuildAttemptResource) -> ExecutorReceipt | None:
    try:
        receipt = group.dispatcher.runner.query(original.identity.reservation_id)
    except (OSError, TimeoutError):
        return None
    if receipt is not None and (
            receipt.identity != original.identity or receipt.request_digest != original.request_digest
            or receipt.process_binding not in {None, original.process_binding}):
        raise ProbeFailure("engineering_build_resource_binding_mismatch")
    return receipt


def confirmed_stop(receipt: ExecutorReceipt | None) -> ExecutorReceipt | None:
    if receipt is not None and receipt.disk_reclaimed and (
            receipt.state == "closed_unstarted" or (
                receipt.state == "stopped" and receipt.evidence.get("process_group_removed") is True
                and receipt.evidence.get("runtime_tmpfs_reclaimed") is True)):
        return receipt
    return None
