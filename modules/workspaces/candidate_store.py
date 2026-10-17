"""Stable physical candidate capture and reconciliation, without business grants."""

import os
from contextlib import contextmanager

import rfc8785
from pydantic import Field

from modules.workspaces import candidate_content, candidate_git, file_journal
from modules.workspaces.candidate_freeze import CandidateFreezeController
from modules.workspaces.safe_paths import (
    PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular, write_new_file,
)
from modules.workspaces.workfiles import _read_receipt, _storage_id
from modules.workspaces.workspace_views import observe
from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p1.workspace_candidates import (
    CandidateFreezeReceipt, CandidateFreezeSpec, CandidateFreezeStatus, candidate_freeze_digest,
)
from packages.contracts.p1.workspace_git import CandidateSnapshot, StorageId, content_digest, manifest_bytes

_LIMIT = 256


class _CandidateIntent(Contract):
    operation_id: Identifier
    request_digest: Digest
    spec: CandidateFreezeSpec
    storage_id: StorageId
    stage_name: str = Field(pattern=r"^stage-[0-9a-f]{64}$")


def _candidate_id(spec):
    return "candidate-" + content_digest(rfc8785.dumps([spec.binding.project_id, spec.candidate_id]))[7:]


def _intent(operation_id, spec):
    return _CandidateIntent(operation_id=operation_id, request_digest=candidate_freeze_digest(spec), spec=spec,
                            storage_id=_candidate_id(spec),
                            stage_name="stage-" + content_digest(rfc8785.dumps(operation_id))[7:])


class CandidateStore:
    """Only a trusted resolver supplies current authority, inputs and real limits.

    workspace_root comes from controlled storage admission and is shared with
    WorkspaceFileService. The caller keeps that admission for the complete call.
    Registered Runner readers are read-only; this is not a general process-stop
    or final integration/acceptance service. Unknown operations are reconciled
    against retained bytes and stable Git objects, never recaptured from live files.
    """

    def __init__(self, workspace_root, git, resolve_operation, freeze_controller):
        if not callable(resolve_operation):
            raise WorkspaceFileError("operation_resolver_required")
        if type(freeze_controller) is not CandidateFreezeController:
            raise WorkspaceFileError("workspace_freeze_controller_required")
        self._root, self._git, self._resolver = PrivateRoot(workspace_root), git, resolve_operation
        self._freeze = freeze_controller
        with self._root.exclusive() as root:
            for path in ("candidate-operations", "candidates", "file-operations"):
                with directory_at(root, path, create=True):
                    pass

    def _current(self, operation_id):
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 160:
            raise WorkspaceFileError("workspace_operation_invalid")
        try:
            spec = self._resolver(operation_id)
        except LookupError:
            raise WorkspaceFileError("workspace_operation_unregistered") from None
        if type(spec) is not CandidateFreezeSpec:
            raise WorkspaceFileError("workspace_operation_kind_invalid")
        try:
            return CandidateFreezeSpec.model_validate(spec.model_dump())
        except ValueError:
            raise WorkspaceFileError("workspace_operation_invalid") from None

    def _still_current(self, operation_id, spec):
        if self._current(operation_id) != spec:
            raise WorkspaceFileError("workspace_operation_binding_mismatch")

    @contextmanager
    def _workspace(self, root, spec):
        initial = _read_receipt(root, _storage_id(spec.binding))
        excluded = {"workspace_revision", "write_generation"}
        if (initial.operation_id != spec.materialization_operation_id
                or initial.binding.model_dump(exclude=excluded) != spec.binding.model_dump(exclude=excluded)):
            raise WorkspaceFileError("workspace_binding_mismatch")
        if spec.binding.workspace_revision < initial.binding.workspace_revision:
            raise WorkspaceFileError("workspace_revision_stale")
        if spec.binding.write_generation < initial.binding.write_generation:
            raise WorkspaceFileError("workspace_generation_stale")
        for intent, receipt in file_journal.records(root):
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
        with directory_at(root, initial.storage_id + "/files") as files:
            yield files

    def _source(self, spec):
        binding = spec.binding
        return self._git.resolve_source(binding.project_id, binding.source_id, binding.source_revision)

    def _verified(self, stored, intent, *, require_ref):
        receipt, manifest = candidate_content.verify(stored, intent)
        source = self._source(intent.spec)
        with self._git.candidate_repository(source, intent.spec.binding.base_commit) as (metadata, _):
            candidate_git.verify(metadata, source, manifest, intent.spec, intent.operation_id,
                                 receipt.snapshot.candidate_commit, require_ref=require_ref)
        return receipt

    def _reconcile(self, root, intent):
        with directory_at(root, "candidates") as candidates:
            if exists_at(candidates, intent.storage_id):
                with directory_at(candidates, intent.storage_id) as stored:
                    return self._verified(stored, intent, require_ref=True)
            if not exists_at(candidates, intent.stage_name):
                raise WorkspaceFileError("candidate_capture_unconfirmed")
            with directory_at(candidates, intent.stage_name) as stored:
                receipt = self._verified(stored, intent, require_ref=False)
            self._still_current(intent.operation_id, intent.spec)
            source = self._source(intent.spec)
            with self._git.candidate_repository(source, intent.spec.binding.base_commit) as (metadata, _):
                candidate_git.retain(metadata, intent.operation_id, receipt.snapshot.candidate_commit)
            self._still_current(intent.operation_id, intent.spec)
            os.rename(intent.stage_name, intent.storage_id, src_dir_fd=candidates, dst_dir_fd=candidates)
            os.fsync(candidates)
            return receipt

    def _query(self, root, operation_id, spec):
        expected = _intent(operation_id, spec)
        result = CandidateFreezeStatus(operation_id=operation_id, request_digest=expected.request_digest, state="not_found")
        with directory_at(root, "candidate-operations") as operations:
            name = file_journal.operation_name(operation_id)
            if not exists_at(operations, name):
                return result
            try:
                with directory_at(operations, name) as operation:
                    intent = _CandidateIntent.model_validate_json(read_regular(operation, "intent.json", 65536))
            except (WorkspaceFileError, ValueError):
                return result.model_copy(update={"state": "unknown", "reason_code": "candidate_journal_invalid"})
            if intent != expected:
                raise WorkspaceFileError("candidate_request_digest_conflict")
        try:
            receipt = self._reconcile(root, intent)
            return CandidateFreezeStatus(operation_id=operation_id, request_digest=expected.request_digest,
                                         state="captured", receipt=receipt)
        except WorkspaceFileError as error:
            return result.model_copy(update={"state": "unknown", "reason_code": error.code})
        except OSError:
            return result.model_copy(update={"state": "unknown", "reason_code": "candidate_capture_unconfirmed"})

    def query(self, operation_id):
        with self._root.exclusive() as root:
            return self._query(root, operation_id, self._current(operation_id))

    def _prepare(self, root, operation_id, spec):
        intent = _intent(operation_id, spec)
        with directory_at(root, "candidate-operations") as operations:
            if len(os.listdir(operations)) >= _LIMIT:
                raise WorkspaceFileError("candidate_journal_limit_exceeded")
            with directory_at(operations, file_journal.operation_name(operation_id), create=True) as operation:
                file_journal.write_record(operation, "intent.json", intent)
        return intent

    def _stage(self, root, files, intent, handle, observation):
        spec = intent.spec
        with directory_at(root, "candidates") as candidates:
            if exists_at(candidates, intent.storage_id) or exists_at(candidates, intent.stage_name):
                raise WorkspaceFileError("candidate_identity_conflict")
            os.mkdir(intent.stage_name, 0o700, dir_fd=candidates)
            with directory_at(candidates, intent.stage_name) as stored:
                os.mkdir("files", 0o755, dir_fd=stored)
                with directory_at(stored, "files") as saved:
                    candidate_content.copy_files(files, saved, observation.manifest)
                    self._still_current(intent.operation_id, spec)
                    self._freeze.validate(handle, root, files)
                    if observe(files) != observation:
                        raise WorkspaceFileError("candidate_content_changed")
                    source = self._source(spec)
                    with self._git.candidate_repository(source, spec.binding.base_commit) as (metadata, _):
                        commit = candidate_git.prepare(metadata, source, saved, observation.manifest, spec, intent.operation_id)
                self._still_current(intent.operation_id, spec)
                self._freeze.validate(handle, root, files)
                if observe(files) != observation:
                    raise WorkspaceFileError("candidate_content_changed")
                receipt = CandidateFreezeReceipt(
                    operation_id=intent.operation_id, request_digest=intent.request_digest,
                    snapshot=CandidateSnapshot(binding=spec.binding, candidate_id=spec.candidate_id,
                        candidate_commit=commit, parent_commit=spec.binding.base_commit,
                        freeze_operation_id=intent.operation_id, storage_id=intent.storage_id,
                        manifest_digest=spec.expected_manifest_digest),
                    materialization_operation_id=spec.materialization_operation_id, runtime_scope_id=spec.runtime_scope_id,
                    writer_scope_digest=handle.proof.writer_scope_digest, file_count=len(observation.manifest.files),
                    total_bytes=sum(item.size_bytes for item in observation.manifest.files), observed_at=handle.proof.observed_at,
                )
                write_new_file(stored, "manifest.json", manifest_bytes(observation.manifest.files))
                write_new_file(stored, "writer-proof.json", handle.proof.model_dump_json().encode("utf-8"))
                write_new_file(stored, "receipt.json", receipt.model_dump_json().encode("utf-8"))
                candidate_content.seal(stored)
            os.fsync(candidates)

    def capture(self, operation_id):
        with self._root.exclusive() as root:
            spec = self._current(operation_id)
            original = self._query(root, operation_id, spec)
            if original.state == "captured":
                return original.receipt
            if original.state != "not_found":
                raise WorkspaceFileError("candidate_capture_pending_reconciliation")
            with directory_at(root, "candidates") as candidates:
                if exists_at(candidates, _candidate_id(spec)):
                    raise WorkspaceFileError("candidate_identity_conflict")
            with self._workspace(root, spec) as files:
                with self._freeze.freeze(root, files, spec.binding, spec.runtime_scope_id) as handle:
                    observation = observe(files)
                    if observation.digest != spec.expected_manifest_digest:
                        raise WorkspaceFileError("candidate_manifest_conflict")
                    self._still_current(operation_id, spec)
                    intent = self._prepare(root, operation_id, spec)
                    try:
                        self._stage(root, files, intent, handle, observation)
                        self._still_current(operation_id, spec)
                        return self._reconcile(root, intent)
                    except WorkspaceFileError as error:
                        if error.code in {"storage_path_unavailable", "storage_write_failed", "storage_file_unavailable"}:
                            raise WorkspaceFileError("candidate_capture_unconfirmed") from None
                        raise
                    except OSError:
                        raise WorkspaceFileError("candidate_capture_unconfirmed") from None

    @contextmanager
    def open_candidate(self, operation_id):
        with self._root.exclusive() as root:
            spec = self._current(operation_id)
            status = self._query(root, operation_id, spec)
            if status.state != "captured":
                raise WorkspaceFileError("candidate_capture_pending_reconciliation")
            with directory_at(root, "candidates/" + status.receipt.snapshot.storage_id + "/files") as files:
                yield status.receipt, files

    def close(self):
        self._root.close()
