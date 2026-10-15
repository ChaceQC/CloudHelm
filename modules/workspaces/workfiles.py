"""Initial independent file views; admission and runtime readiness remain external."""

import hashlib
import os
from collections.abc import Callable
from uuid import uuid4

import rfc8785

from modules.workspaces.git_objects import GitObjectStore
from modules.workspaces.safe_paths import (
    PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular,
    remove_staging, write_new_file,
)
from packages.contracts.p1.workspace_git import (
    WorkspaceBinding, WorkspaceFiles, WorkspaceManifest, content_digest, manifest_bytes,
)


def _storage_id(binding: WorkspaceBinding) -> str:
    digest = hashlib.sha256(rfc8785.dumps([binding.project_id, binding.workspace_id])).hexdigest()
    return "workspace-" + digest


def _validated_binding(binding: WorkspaceBinding) -> WorkspaceBinding:
    if type(binding) is not WorkspaceBinding:
        raise WorkspaceFileError("workspace_binding_invalid")
    try:
        return WorkspaceBinding.model_validate(binding.model_dump())
    except ValueError:
        raise WorkspaceFileError("workspace_binding_invalid") from None


def _read_receipt(root: int, storage_id: str) -> WorkspaceFiles:
    with directory_at(root, storage_id) as stored:
        try:
            receipt = WorkspaceFiles.model_validate_json(read_regular(stored, "receipt.json", 65536))
        except ValueError:
            raise WorkspaceFileError("workspace_receipt_invalid") from None
        manifest = read_regular(stored, "manifest.json", 8 * 1024 * 1024)
        if receipt.storage_id != storage_id or content_digest(manifest) != receipt.manifest_digest:
            raise WorkspaceFileError("workspace_receipt_mismatch")
        try:
            entries = WorkspaceManifest.model_validate_json(manifest).files
        except ValueError:
            raise WorkspaceFileError("workspace_manifest_invalid") from None
        if (manifest != manifest_bytes(entries) or receipt.file_count != len(entries)
                or receipt.total_bytes != sum(item.size_bytes for item in entries)):
            raise WorkspaceFileError("workspace_receipt_mismatch")
        with directory_at(stored, "files"):
            pass
        return receipt


class WorkfileStore:
    """Resolve original operations through the trusted application, never booleans.

    The resolver must read registered operation identity, current domain gates and
    real development limits. It is invoked before any work and again before publish.
    This class neither authenticates callers nor provides physical storage quotas.
    """

    def __init__(self, storage_root, git: GitObjectStore,
                 resolve_operation: Callable[[str], WorkspaceBinding]):
        if not callable(resolve_operation):
            raise WorkspaceFileError("operation_resolver_required")
        self._root = PrivateRoot(storage_root)
        self._git = git
        self._resolve_operation = resolve_operation

    def _check_operation(self, binding: WorkspaceBinding, operation_id: str) -> None:
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 160:
            raise WorkspaceFileError("workspace_operation_invalid")
        try:
            current = self._resolve_operation(operation_id)
        except LookupError:
            raise WorkspaceFileError("workspace_operation_unregistered") from None
        if type(current) is not WorkspaceBinding or current != binding:
            raise WorkspaceFileError("workspace_operation_binding_mismatch")

    def materialize(self, binding: WorkspaceBinding, operation_id: str) -> WorkspaceFiles:
        binding = _validated_binding(binding)
        storage_id = _storage_id(binding)
        with self._root.exclusive() as root:
            self._check_operation(binding, operation_id)
            if exists_at(root, storage_id):
                receipt = _read_receipt(root, storage_id)
                if receipt.binding != binding or receipt.operation_id != operation_id:
                    raise WorkspaceFileError("workspace_materialization_conflict")
                return receipt
            source = self._git.resolve_source(binding.project_id, binding.source_id, binding.source_revision)
            with self._git.open_commit(source, binding.base_commit) as (tree, read_file):
                return self._publish(root, binding, operation_id, storage_id, tree, read_file)

    def _publish(self, root, binding, operation_id, storage_id, tree, read_file):
        self._check_operation(binding, operation_id)
        staged, published = "stage-" + uuid4().hex, False
        os.mkdir(staged, 0o700, dir_fd=root)
        try:
            with directory_at(root, staged) as staging:
                os.mkdir("files", 0o755, dir_fd=staging)
                with directory_at(staging, "files") as files:
                    for entry in tree.files:
                        write_new_file(files, entry.path, read_file(entry), executable=entry.mode == "100755")
                    os.fsync(files)
                receipt = WorkspaceFiles(
                    binding=binding, operation_id=operation_id, storage_id=storage_id,
                    manifest_digest=tree.manifest_digest, file_count=len(tree.files), total_bytes=tree.total_bytes,
                )
                write_new_file(staging, "manifest.json", manifest_bytes(tree.files))
                write_new_file(staging, "receipt.json", receipt.model_dump_json().encode("utf-8"))
                os.fsync(staging)
            self._check_operation(binding, operation_id)
            if exists_at(root, storage_id):
                raise WorkspaceFileError("workspace_materialization_conflict")
            os.rename(staged, storage_id, src_dir_fd=root, dst_dir_fd=root)
            published = True
            os.fsync(root)
            return receipt
        except OSError:
            raise WorkspaceFileError("workspace_materialization_unconfirmed") from None
        finally:
            if not published and exists_at(root, staged):
                remove_staging(root, staged)

    def query(self, binding: WorkspaceBinding, operation_id: str) -> WorkspaceFiles:
        """Return only the original receipt; later edits do not rewrite its digest."""
        binding = _validated_binding(binding)
        with self._root.exclusive() as root:
            self._check_operation(binding, operation_id)
            receipt = _read_receipt(root, _storage_id(binding))
            if receipt.binding != binding or receipt.operation_id != operation_id:
                raise WorkspaceFileError("workspace_materialization_conflict")
            return receipt

    def close(self) -> None:
        self._root.close()
