"""Service-only single-file operations; database revisions remain Hub authority."""

import os
from contextlib import contextmanager

from modules.workspaces import file_journal as journal
from modules.workspaces.git_objects import _check_content
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular
from modules.workspaces.workfiles import _read_receipt, _storage_id
from modules.workspaces.workspace_views import (
    diff_result, file_parent, file_state, observe, project_change, status_result,
)
from packages.contracts.p1.workspace_git import (
    WorkspaceManifest, WorkspaceMutationSpec, WorkspaceMutationStatus, WorkspaceReadSpec,
    content_digest, workspace_mutation_digest, workspace_path,
)


class WorkspaceFileService:
    """Resolver owns current permissions, Task/write gates, versions and real limits.

    This slice requires service-owned writers using the same root lock; it does not
    grant Runner write access, establish a freeze, or commit a database revision.
    Replacement/deletion retain bytes in the journal; no disk release is claimed.
    """

    def __init__(self, storage_root, git, resolve_operation):
        if not callable(resolve_operation):
            raise WorkspaceFileError("operation_resolver_required")
        self._root, self._git, self._resolver = PrivateRoot(storage_root), git, resolve_operation
        with self._root.exclusive() as root:
            with directory_at(root, "file-operations", create=True):
                pass

    def _current(self, operation_id, kind):
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 160:
            raise WorkspaceFileError("workspace_operation_invalid")
        try:
            spec = self._resolver(operation_id)
        except LookupError:
            raise WorkspaceFileError("workspace_operation_unregistered") from None
        if type(spec) is not kind:
            raise WorkspaceFileError("workspace_operation_kind_invalid")
        data = spec.model_dump()
        if kind is WorkspaceMutationSpec:
            data["content"] = spec.content
        try:
            return kind.model_validate(data)
        except ValueError:
            raise WorkspaceFileError("workspace_operation_invalid") from None

    @contextmanager
    def _workspace(self, root, spec):
        initial = _read_receipt(root, _storage_id(spec.binding))
        excluded = {"workspace_revision", "write_generation"}
        if (initial.operation_id != spec.materialization_operation_id or
                initial.binding.model_dump(exclude=excluded) != spec.binding.model_dump(exclude=excluded)):
            raise WorkspaceFileError("workspace_binding_mismatch")
        if spec.binding.workspace_revision < initial.binding.workspace_revision:
            raise WorkspaceFileError("workspace_revision_stale")
        if spec.binding.write_generation < initial.binding.write_generation:
            raise WorkspaceFileError("workspace_generation_stale")
        with directory_at(root, initial.storage_id) as stored:
            base = WorkspaceManifest.model_validate_json(read_regular(stored, "manifest.json", 8 * 1024 * 1024))
            with directory_at(stored, "files") as files:
                yield files, initial, base

    def _guard(self, root, spec):
        records = journal.records(root)
        if len(records) >= journal.JOURNAL_LIMIT:
            raise WorkspaceFileError("workspace_journal_limit_exceeded")
        for intent, receipt in records:
            if intent is None:
                raise WorkspaceFileError("workspace_file_pending_reconciliation")
            if (intent.binding.project_id, intent.binding.workspace_id) != (spec.binding.project_id, spec.binding.workspace_id):
                continue
            if receipt is None:
                raise WorkspaceFileError("workspace_file_pending_reconciliation")
            if receipt.outcome == "applied":
                if spec.binding.workspace_revision <= receipt.binding.workspace_revision:
                    raise WorkspaceFileError("workspace_revision_stale")
                if spec.binding.write_generation < receipt.binding.write_generation:
                    raise WorkspaceFileError("workspace_generation_stale")

    def _query(self, root, operation_id, spec):
        result = WorkspaceMutationStatus(operation_id=operation_id, request_digest=workspace_mutation_digest(spec), state="not_found")
        with directory_at(root, "file-operations") as operations:
            if not exists_at(operations, journal.operation_name(operation_id)):
                return result
            with directory_at(operations, journal.operation_name(operation_id)) as operation:
                try:
                    intent = journal.read_intent(operation)
                except WorkspaceFileError:
                    return result.model_copy(update={"state": "unknown", "reason_code": "workspace_journal_invalid"})
                if (intent.operation_id != operation_id or intent.request_digest != result.request_digest
                        or intent.binding != spec.binding or intent.materialization_operation_id != spec.materialization_operation_id
                        or intent.path != spec.path or intent.action != spec.action or intent.before_file != spec.expected_file
                        or intent.replacement != spec.replacement or intent.before_manifest_digest != spec.expected_manifest_digest):
                    raise WorkspaceFileError("workspace_request_digest_conflict")
                try:
                    receipt = journal.read_receipt(operation, intent)
                    if receipt is not None:
                        return result.model_copy(update={"state": receipt.outcome, "receipt": receipt})
                    with self._workspace(root, spec) as (files, _, _):
                        state, target, receipt = journal.reconcile(files, operation, intent)
                    return result.model_copy(update={"state": state, "target_state": target, "receipt": receipt})
                except WorkspaceFileError as error:
                    return result.model_copy(update={"state": "unknown", "reason_code": error.code})

    def query(self, operation_id):
        with self._root.exclusive() as root:
            return self._query(root, operation_id, self._current(operation_id, WorkspaceMutationSpec))

    def _abort(self, files, operation, intent):
        try:
            if observe(files).digest == intent.before_manifest_digest and file_state(files, intent.path)[1] == intent.old_proof:
                journal.write_record(operation, "receipt.json", journal.receipt_for(intent, "not_applied"))
        except (WorkspaceFileError, OSError):
            pass  # An unconfirmed terminal record leaves the operation blocking.

    def _apply(self, root, operation_id, spec):
        original = self._query(root, operation_id, spec)
        if original.state != "not_found":
            if original.receipt is not None:
                return original.receipt
            raise WorkspaceFileError("workspace_file_pending_reconciliation")
        with self._workspace(root, spec) as (files, _, _):
            self._guard(root, spec)
            current = observe(files)
            actual = next((entry for entry in current.manifest.files if entry.path == spec.path), None)
            if current.digest != spec.expected_manifest_digest or actual != spec.expected_file:
                raise WorkspaceFileError("workspace_file_conflict")
            with file_parent(files, spec.path):
                pass  # Creating directories is deliberately a separate operation.
            if spec.path.split("/")[-1].casefold() in {".gitmodules", ".lfsconfig"}:
                raise WorkspaceFileError("git_extension_unsupported")
            if spec.action == "write":
                _check_content(spec.path, spec.content)
            project_change(current, spec.path, spec.replacement)
            if self._current(operation_id, WorkspaceMutationSpec) != spec:
                raise WorkspaceFileError("workspace_operation_binding_mismatch")
            intent = journal.prepare(root, operation_id, spec, current)
            with directory_at(root, "file-operations/" + journal.operation_name(operation_id)) as operation:
                attempted = False
                try:
                    if observe(files).digest != intent.before_manifest_digest:
                        raise WorkspaceFileError("workspace_file_conflict")
                    if self._current(operation_id, WorkspaceMutationSpec) != spec:
                        raise WorkspaceFileError("workspace_operation_binding_mismatch")
                    attempted = True
                    journal.publish(files, operation, intent)
                    state, _, receipt = journal.reconcile(files, operation, intent)
                    if state != "applied":
                        raise WorkspaceFileError("workspace_file_unconfirmed")
                    return receipt
                except WorkspaceFileError as error:
                    if not attempted:
                        self._abort(files, operation, intent)
                    elif error.code == "storage_path_unavailable":
                        raise WorkspaceFileError("workspace_file_unconfirmed") from None
                    raise
                except OSError:
                    raise WorkspaceFileError("workspace_file_unconfirmed") from None

    def apply(self, operation_id):
        with self._root.exclusive() as root:
            try:
                return self._apply(root, operation_id, self._current(operation_id, WorkspaceMutationSpec))
            except OSError:
                raise WorkspaceFileError("workspace_file_unconfirmed") from None

    @contextmanager
    def open_read(self, operation_id):
        """Hold the existing private-root lock while an authorized reader observes files."""
        with self._root.exclusive() as root:
            spec = self._current(operation_id, WorkspaceReadSpec)
            with self._workspace(root, spec) as (files, _, _):
                yield files, spec.binding

    def status(self, operation_id, paths=()):
        if not isinstance(paths, (tuple, list)) or len(paths) > 32:
            raise WorkspaceFileError("workspace_path_limit_exceeded")
        try:
            paths = tuple(workspace_path(path) for path in paths)
        except ValueError:
            raise WorkspaceFileError("workspace_path_invalid") from None
        with self._root.exclusive() as root:
            spec = self._current(operation_id, WorkspaceReadSpec)
            with self._workspace(root, spec) as (files, initial, base):
                unresolved = sum(intent is None or receipt is None and intent.binding.workspace_id == spec.binding.workspace_id
                                 and intent.binding.project_id == spec.binding.project_id for intent, receipt in journal.records(root))
                return status_result(spec, initial, base, observe(files), paths, unresolved)

    def diff(self, operation_id, path, *, expected_manifest_digest=None):
        try:
            path = workspace_path(path)
        except ValueError:
            raise WorkspaceFileError("workspace_path_invalid") from None
        with self._root.exclusive() as root:
            spec = self._current(operation_id, WorkspaceReadSpec)
            with self._workspace(root, spec) as (files, _, base):
                current = observe(files)
                if expected_manifest_digest is not None and current.digest != expected_manifest_digest:
                    raise WorkspaceFileError("workspace_manifest_mismatch")
                before = next((entry for entry in base.files if entry.path == path), None)
                after = next((entry for entry in current.manifest.files if entry.path == path), None)
                old, new = b"", b""
                if before is not None:
                    old = None
                    if before.size_bytes <= 65536:
                        source = self._git.resolve_source(spec.binding.project_id, spec.binding.source_id, spec.binding.source_revision)
                        with self._git.open_commit(source, spec.binding.base_commit) as (tree, reader):
                            entry = next((item for item in tree.files if item.path == path), None)
                            if entry is None or entry.content_digest != before.content_digest:
                                raise WorkspaceFileError("workspace_initial_manifest_mismatch")
                            old = reader(entry)
                if after is not None:
                    new = read_regular(files, path, 65536) if after.size_bytes <= 65536 else None
                    if new is not None and content_digest(new) != after.content_digest:
                        raise WorkspaceFileError("workspace_file_changed")
                return diff_result(spec.binding, path, before, after, old, new)

    def close(self):
        self._root.close()
