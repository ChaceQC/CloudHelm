"""Bounded durable single-file intent/results and fd-relative atomic publication."""

import ctypes
import os
from datetime import UTC, datetime
from uuid import uuid4

import rfc8785
from pydantic import Field

from modules.workspaces.safe_paths import WorkspaceFileError, directory_at, exists_at, read_regular, write_new_file
from modules.workspaces.workspace_views import Fingerprint, file_parent, file_state, fingerprint, observe, project_change
from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.workspace_git import (
    WorkspaceBinding, WorkspaceFile, WorkspaceMutationReceipt, content_digest, manifest_bytes, workspace_mutation_digest,
)

JOURNAL_LIMIT = 256


class FileIntent(Contract):
    operation_id: Identifier
    request_digest: Digest
    binding: WorkspaceBinding
    materialization_operation_id: Identifier
    action: str = Field(pattern=r"^(write|delete)$")
    path: str
    before_file: WorkspaceFile | None
    replacement: WorkspaceFile | None
    before_manifest_digest: Digest
    after_manifest_digest: Digest
    old_proof: Fingerprint | None
    staged_proof: Fingerprint | None
    prepared_at: UtcTimestamp


def operation_name(operation_id: str) -> str:
    return "operation-" + content_digest(rfc8785.dumps(operation_id))[7:]


def _rename(source_fd: int, source: str, destination_fd: int, destination: str, *, exchange: bool = False):
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise WorkspaceFileError("workspace_atomic_rename_unsupported") from None
    function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    code = function(source_fd, source.encode("utf-8"), destination_fd, destination.encode("utf-8"), 2 if exchange else 1)
    if code != 0:
        raise OSError(ctypes.get_errno(), "workspace atomic rename failed")


def write_record(directory: int, name: str, value: Contract):
    staged = "record-" + uuid4().hex
    write_new_file(directory, staged, value.model_dump_json().encode("utf-8"))
    _rename(directory, staged, directory, name)
    os.fsync(directory)


def read_intent(operation: int) -> FileIntent:
    try:
        return FileIntent.model_validate_json(read_regular(operation, "intent.json", 65536))
    except ValueError:
        raise WorkspaceFileError("workspace_journal_invalid") from None


def receipt_for(intent: FileIntent, outcome: str, observed_at: str | None = None) -> WorkspaceMutationReceipt:
    return WorkspaceMutationReceipt(
        operation_id=intent.operation_id, request_digest=intent.request_digest, binding=intent.binding,
        materialization_operation_id=intent.materialization_operation_id, action=intent.action, path=intent.path,
        outcome=outcome, before_file=intent.before_file,
        after_file=intent.replacement if outcome == "applied" else intent.before_file,
        before_manifest_digest=intent.before_manifest_digest,
        after_manifest_digest=intent.after_manifest_digest if outcome == "applied" else intent.before_manifest_digest,
        observed_at=observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def read_receipt(operation: int, intent: FileIntent) -> WorkspaceMutationReceipt | None:
    if not exists_at(operation, "receipt.json"):
        return None
    try:
        receipt = WorkspaceMutationReceipt.model_validate_json(read_regular(operation, "receipt.json", 65536))
        if receipt != receipt_for(intent, receipt.outcome, receipt.observed_at):
            raise ValueError
        return receipt
    except ValueError:
        raise WorkspaceFileError("workspace_journal_invalid") from None


def records(root: int):
    result = []
    with directory_at(root, "file-operations") as operations:
        names = os.listdir(operations)
        if len(names) > JOURNAL_LIMIT:
            raise WorkspaceFileError("workspace_journal_limit_exceeded")
        for name in names:
            try:
                with directory_at(operations, name) as operation:
                    intent = read_intent(operation)
                    if operation_name(intent.operation_id) != name:
                        raise WorkspaceFileError("workspace_journal_invalid")
                    result.append((intent, read_receipt(operation, intent)))
            except WorkspaceFileError:
                result.append((None, None))
    return result


def prepare(root: int, operation_id: str, spec, observation) -> FileIntent:
    with directory_at(root, "file-operations/" + operation_name(operation_id), create=True) as operation:
        staged = None
        if spec.action == "write":
            write_new_file(operation, "payload", spec.content, executable=spec.replacement.mode == "100755")
            staged = fingerprint(os.stat("payload", dir_fd=operation, follow_symlinks=False))
        projected = project_change(observation, spec.path, spec.replacement)
        intent = FileIntent(
            operation_id=operation_id, request_digest=workspace_mutation_digest(spec), binding=spec.binding,
            materialization_operation_id=spec.materialization_operation_id, action=spec.action, path=spec.path,
            before_file=spec.expected_file, replacement=spec.replacement,
            before_manifest_digest=observation.digest, after_manifest_digest=content_digest(manifest_bytes(projected.files)),
            old_proof=observation.fingerprints.get(spec.path), staged_proof=staged,
            prepared_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        write_record(operation, "intent.json", intent)
        return intent


def publish(files: int, operation: int, intent: FileIntent):
    current, proof = file_state(files, intent.path)
    if current != intent.before_file or proof != intent.old_proof:
        raise WorkspaceFileError("workspace_file_conflict")
    with file_parent(files, intent.path) as (parent, name):
        if intent.action == "delete":
            _rename(parent, name, operation, "removed")
        else:
            _rename(operation, "payload", parent, name, exchange=intent.before_file is not None)
        os.fsync(parent)
        os.fsync(operation)


def _retained(operation: int, name: str, path: str):
    entry, proof = file_state(operation, name)
    return (entry.model_copy(update={"path": path}) if entry else None), proof


def _same_inode(actual, expected) -> bool:
    # rename may change ctime; mode/size/mtime and the verified content still match.
    return actual is not None and expected is not None and actual[:5] == expected[:5]


def reconcile(files: int, operation: int, intent: FileIntent):
    """Observe only; old/unknown states never execute the original write again."""
    try:
        current, proof = file_state(files, intent.path)
        retained, retained_proof = _retained(operation, "removed" if intent.action == "delete" else "payload", intent.path)
        if intent.action == "delete":
            applied = current is None and retained == intent.before_file and _same_inode(retained_proof, intent.old_proof)
            old = current == intent.before_file and proof == intent.old_proof and retained is None
        else:
            applied = current == intent.replacement and _same_inode(proof, intent.staged_proof)
            if intent.before_file is None:
                applied = applied and retained is None
            else:
                applied = applied and retained == intent.before_file and _same_inode(retained_proof, intent.old_proof)
            old = current == intent.before_file and proof == intent.old_proof and retained == intent.replacement and retained_proof == intent.staged_proof
        if applied and observe(files).digest == intent.after_manifest_digest:
            receipt = receipt_for(intent, "applied")
            write_record(operation, "receipt.json", receipt)
            return "applied", "new", receipt
        return ("pending", "old", None) if old else ("unknown", "other", None)
    except WorkspaceFileError:
        return "unknown", "unavailable", None
    except OSError:
        raise WorkspaceFileError("workspace_file_unconfirmed") from None
