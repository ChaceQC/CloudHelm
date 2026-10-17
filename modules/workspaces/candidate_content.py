"""Verified independent candidate bytes and manifest, kept outside live source."""

import os
import stat

from modules.workspaces.safe_paths import (
    WorkspaceFileError, directory_at, read_regular, write_new_file,
)
from modules.workspaces.workspace_views import observe
from packages.contracts.p1.workspace_candidates import CandidateFreezeReceipt, WorkspaceFreezeProof
from packages.contracts.p1.workspace_git import WorkspaceManifest, content_digest, manifest_bytes


def copy_files(source, destination, manifest):
    for entry in manifest.files:
        data = read_regular(source, entry.path, entry.size_bytes)
        if len(data) != entry.size_bytes or content_digest(data) != entry.content_digest:
            raise WorkspaceFileError("candidate_content_changed")
        write_new_file(destination, entry.path, data, executable=entry.mode == "100755")
    if observe(destination).digest != content_digest(manifest_bytes(manifest.files)):
        raise WorkspaceFileError("candidate_content_changed")


def seal(directory):
    for name in os.listdir(directory):
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with directory_at(directory, name) as child:
                seal(child)
        elif stat.S_ISREG(info.st_mode):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            try:
                os.fchmod(descriptor, 0o555 if info.st_mode & 0o111 else 0o444)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        else:
            raise WorkspaceFileError("candidate_content_invalid")
    os.fchmod(directory, 0o555)
    os.fsync(directory)


def _readonly(directory):
    if os.fstat(directory).st_mode & 0o222:
        raise WorkspaceFileError("candidate_content_not_readonly")
    for name in os.listdir(directory):
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if info.st_mode & 0o222:
            raise WorkspaceFileError("candidate_content_not_readonly")
        if stat.S_ISDIR(info.st_mode):
            with directory_at(directory, name) as child:
                _readonly(child)
        elif not stat.S_ISREG(info.st_mode):
            raise WorkspaceFileError("candidate_content_invalid")


def verify(stored, intent):
    try:
        if set(os.listdir(stored)) != {"files", "manifest.json", "receipt.json", "writer-proof.json"}:
            raise WorkspaceFileError("candidate_content_invalid")
        receipt = CandidateFreezeReceipt.model_validate_json(read_regular(stored, "receipt.json", 65536))
        proof = WorkspaceFreezeProof.model_validate_json(read_regular(stored, "writer-proof.json", 65536))
        raw = read_regular(stored, "manifest.json", 8 * 1024 * 1024)
        manifest = WorkspaceManifest.model_validate_json(raw)
        spec, snapshot = intent.spec, receipt.snapshot
        if (receipt.operation_id != intent.operation_id or receipt.request_digest != intent.request_digest
                or snapshot.binding != spec.binding or snapshot.candidate_id != spec.candidate_id
                or snapshot.parent_commit != spec.binding.base_commit or snapshot.storage_id != intent.storage_id
                or snapshot.manifest_digest != spec.expected_manifest_digest or content_digest(raw) != snapshot.manifest_digest
                or raw != manifest_bytes(manifest.files) or receipt.materialization_operation_id != spec.materialization_operation_id
                or receipt.runtime_scope_id != spec.runtime_scope_id or proof.runtime_scope_id != spec.runtime_scope_id
                or receipt.writer_scope_digest != proof.writer_scope_digest or receipt.observed_at != proof.observed_at
                or receipt.file_count != len(manifest.files)
                or receipt.total_bytes != sum(entry.size_bytes for entry in manifest.files)):
            raise WorkspaceFileError("candidate_receipt_mismatch")
        _readonly(stored)
        with directory_at(stored, "files") as files:
            if observe(files).digest != snapshot.manifest_digest:
                raise WorkspaceFileError("candidate_content_changed")
        return receipt, manifest
    except ValueError as error:
        if isinstance(error, WorkspaceFileError):
            raise
        raise WorkspaceFileError("candidate_receipt_invalid") from None
