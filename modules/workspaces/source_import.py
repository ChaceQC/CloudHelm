"""Trusted, durable reference-r1 imports; public callers supply operation IDs only."""

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import rfc8785
from pydantic import Field, model_validator

from modules.workspaces.git_objects import _inspect, managed_repository_slot
from modules.workspaces.git_process import validate_bare_metadata
from modules.workspaces.reference_seed import (
    REFERENCE_COMMIT, REFERENCE_INPUT_DIGEST, REFERENCE_PREFIX, REFERENCE_REVISION, prepare_reference,
)
from modules.workspaces.safe_paths import (
    PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular, remove_staging, write_new_file,
)
from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.workspace_git import (
    GitFile, GitObjectId, RegisteredGitSource, SourceTree, content_digest, manifest_bytes, workspace_path,
)


class ReferenceImportSpec(Contract):
    source: RegisteredGitSource
    reference_revision: Literal[REFERENCE_REVISION] = REFERENCE_REVISION

    @model_validator(mode="after")
    def check_supported(self):
        if (self.source.kind != "managed_bare" or self.source.object_format != "sha1"
                or self.source.source_prefix or self.source.source_revision != 1):
            raise ValueError("reference_import_mode_unsupported")
        workspace_path(self.source.target_branch)
        return self


def reference_import_digest(spec: ReferenceImportSpec) -> str:
    """Hub stores this exact normalized request digest before admitting the operation."""
    return content_digest(rfc8785.dumps({
        "schema_revision": "p1-reference-import-r1", "source": spec.source.model_dump(mode="json"),
        "reference_revision": spec.reference_revision,
        "seed_commit": REFERENCE_COMMIT, "seed_prefix": REFERENCE_PREFIX,
        "input_set_digest": REFERENCE_INPUT_DIGEST,
    }))


class ReferenceImportReceipt(Contract):
    schema_revision: Literal["p1-reference-import-r1"] = "p1-reference-import-r1"
    operation_id: Identifier
    request_digest: Digest
    source: RegisteredGitSource
    import_commit: GitObjectId
    tree_id: GitObjectId
    seed_commit: Literal[REFERENCE_COMMIT] = REFERENCE_COMMIT
    seed_prefix: Literal[REFERENCE_PREFIX] = REFERENCE_PREFIX
    seed_tree: GitObjectId
    input_set_digest: Literal[REFERENCE_INPUT_DIGEST] = REFERENCE_INPUT_DIGEST
    manifest_digest: Digest
    files: tuple[GitFile, ...] = Field(min_length=32, max_length=32)
    file_count: Literal[32] = 32
    total_bytes: int = Field(strict=True, ge=0)
    prepared_at: UtcTimestamp

    @model_validator(mode="after")
    def check_receipt(self):
        spec = ReferenceImportSpec(source=self.source)
        tree = SourceTree(source=self.source, commit=self.import_commit, tree_id=self.tree_id,
                          files=self.files, manifest_digest=self.manifest_digest)
        if (self.request_digest != reference_import_digest(spec) or self.seed_tree != self.tree_id
                or self.total_bytes != tree.total_bytes):
            raise ValueError("source_import_receipt_mismatch")
        return self


class ReferenceImportStatus(Contract):
    operation_id: Identifier
    request_digest: Digest
    state: Literal["not_found", "pending", "failed", "published"]
    receipt: ReferenceImportReceipt | None = None
    reason_code: str | None = None


class _Intent(Contract):
    operation_id: Identifier
    request_digest: Digest
    spec: ReferenceImportSpec
    stage_id: str = Field(pattern=r"^stage-[0-9a-f]{32}$")
    created_at: UtcTimestamp


class _Failure(Contract):
    reason_code: str = Field(pattern=r"^[a-z0-9_]{1,100}$")
    recorded_at: UtcTimestamp


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _slot(prefix: str, identity: str) -> str:
    return prefix + "-" + content_digest(rfc8785.dumps(identity))[7:]


class ReferenceSourceImporter:
    """Service-private paths and a current-authority resolver, never caller assertions.

    The resolver must enforce that this is the project's initial registered import,
    its current project.manage permission and its real development storage limits.
    Interrupted or failed attempts retain their claim for explicit reconciliation.
    """

    def __init__(self, repository_root, seed_repository,
                 resolve_operation: Callable[[str], ReferenceImportSpec]):
        if not callable(resolve_operation):
            raise WorkspaceFileError("operation_resolver_required")
        self._root = PrivateRoot(repository_root)
        self._seed_repository, self._resolve_operation = seed_repository, resolve_operation
        with self._root.exclusive() as root:
            for path in ("operations", "projects"):
                with directory_at(root, path, create=True):
                    pass

    def _current(self, operation_id: str) -> ReferenceImportSpec:
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 160:
            raise WorkspaceFileError("source_import_operation_invalid")
        try:
            spec = self._resolve_operation(operation_id)
        except LookupError:
            raise WorkspaceFileError("source_import_operation_unregistered") from None
        if type(spec) is not ReferenceImportSpec:
            raise WorkspaceFileError("source_import_spec_invalid")
        try:
            return ReferenceImportSpec.model_validate(spec.model_dump())
        except ValueError:
            raise WorkspaceFileError("source_import_spec_invalid") from None

    def _receipt(self, root: int, intent: _Intent) -> ReferenceImportReceipt:
        with directory_at(root, managed_repository_slot(intent.spec.source)) as repository:
            try:
                receipt = ReferenceImportReceipt.model_validate_json(read_regular(repository, "cloudhelm-import.json", 65536))
            except ValueError:
                raise WorkspaceFileError("source_import_receipt_invalid") from None
            if (receipt.operation_id != intent.operation_id or receipt.request_digest != intent.request_digest
                    or receipt.source != intent.spec.source):
                raise WorkspaceFileError("source_import_receipt_conflict")
            validate_bare_metadata(repository, receipt.source.object_format)
            tree = _inspect(repository, receipt.source, receipt.import_commit, time.monotonic() + 60)
            if (tree.tree_id != receipt.tree_id or tree.files != receipt.files
                    or tree.manifest_digest != receipt.manifest_digest):
                raise WorkspaceFileError("source_import_receipt_mismatch")
            return receipt

    def _status(self, root: int, operation_id: str, spec: ReferenceImportSpec) -> ReferenceImportStatus:
        status = ReferenceImportStatus(operation_id=operation_id, request_digest=reference_import_digest(spec), state="not_found")
        with directory_at(root, "operations") as operations:
            if not exists_at(operations, _slot("import", operation_id)):
                return status
            with directory_at(operations, _slot("import", operation_id)) as operation:
                try:
                    intent = _Intent.model_validate_json(read_regular(operation, "intent.json", 65536))
                except ValueError:
                    return status.model_copy(update={"state": "pending", "reason_code": "source_import_intent_unverified"})
                if (intent.operation_id != operation_id or intent.request_digest != status.request_digest
                        or intent.spec != spec):
                    raise WorkspaceFileError("source_import_request_digest_conflict")
                with directory_at(root, "projects") as projects:
                    try:
                        claim = _Intent.model_validate_json(read_regular(projects, _slot("project", spec.source.project_id) + ".json", 65536))
                    except ValueError:
                        return status.model_copy(update={"state": "pending", "reason_code": "source_import_claim_unverified"})
                    if claim != intent:
                        return status.model_copy(update={"state": "pending", "reason_code": "source_import_claim_conflict"})
                if exists_at(root, managed_repository_slot(spec.source)):
                    try:
                        receipt = self._receipt(root, intent)
                    except WorkspaceFileError as error:
                        return status.model_copy(update={"state": "pending", "reason_code": error.code})
                    return status.model_copy(update={"state": "published", "receipt": receipt})
                if exists_at(operation, "failure.json"):
                    try:
                        failure = _Failure.model_validate_json(read_regular(operation, "failure.json", 4096))
                    except ValueError:
                        return status.model_copy(update={"state": "pending", "reason_code": "source_import_failure_unverified"})
                    return status.model_copy(update={"state": "failed", "reason_code": failure.reason_code})
                return status.model_copy(update={"state": "pending", "reason_code": "source_import_pending_reconciliation"})

    def _record_intent(self, root: int, operation_id: str, spec: ReferenceImportSpec) -> _Intent:
        intent = _Intent(operation_id=operation_id, request_digest=reference_import_digest(spec), spec=spec,
                         stage_id="stage-" + uuid4().hex, created_at=_now())
        with directory_at(root, "projects") as projects:
            if exists_at(projects, _slot("project", spec.source.project_id) + ".json"):
                raise WorkspaceFileError("source_import_project_already_claimed")
            if exists_at(root, managed_repository_slot(spec.source)):
                raise WorkspaceFileError("source_import_repository_already_exists")
            data = intent.model_dump_json().encode("utf-8")
            with directory_at(root, "operations/" + _slot("import", operation_id), create=True) as operation:
                write_new_file(operation, "intent.json", data)
            write_new_file(projects, _slot("project", spec.source.project_id) + ".json", data)
        return intent

    def _prepare(self, root: int, intent: _Intent) -> ReferenceImportReceipt:
        os.mkdir(intent.stage_id, 0o700, dir_fd=root)
        with directory_at(root, intent.stage_id) as staged:
            commit, tree_id, files = prepare_reference(staged, self._seed_repository, intent.spec.source,
                                                       time.monotonic() + 60)
            receipt = ReferenceImportReceipt(
                operation_id=intent.operation_id, request_digest=intent.request_digest, source=intent.spec.source,
                import_commit=commit, tree_id=tree_id, seed_tree=tree_id, files=files,
                manifest_digest=content_digest(manifest_bytes(files)), total_bytes=sum(item.size_bytes for item in files),
                prepared_at=_now(),
            )
            write_new_file(staged, "cloudhelm-import.json", receipt.model_dump_json().encode("utf-8"))
            validate_bare_metadata(staged, "sha1")
            tree = _inspect(staged, receipt.source, receipt.import_commit, time.monotonic() + 60)
            if tree.files != receipt.files or tree.tree_id != receipt.tree_id:
                raise WorkspaceFileError("source_import_receipt_mismatch")
            os.fsync(staged)
            return receipt

    def _perform(self, root: int, intent: _Intent) -> ReferenceImportReceipt:
        publication_attempted = False
        try:
            receipt = self._prepare(root, intent)
            if self._current(intent.operation_id) != intent.spec:
                raise WorkspaceFileError("source_import_operation_binding_mismatch")
            slot = managed_repository_slot(intent.spec.source)
            if exists_at(root, slot):
                raise WorkspaceFileError("source_import_repository_already_exists")
            publication_attempted = True
            os.rename(intent.stage_id, slot, src_dir_fd=root, dst_dir_fd=root)
            os.fsync(root)
            return receipt
        except WorkspaceFileError as error:
            if not publication_attempted and error.code != "git_stop_unconfirmed":
                if exists_at(root, intent.stage_id):
                    remove_staging(root, intent.stage_id)
                with directory_at(root, "operations/" + _slot("import", intent.operation_id)) as operation:
                    failure = _Failure(reason_code=error.code, recorded_at=_now())
                    write_new_file(operation, "failure.json", failure.model_dump_json().encode("utf-8"))
            raise
        except OSError:
            raise WorkspaceFileError("source_import_unconfirmed") from None

    def import_reference(self, operation_id: str) -> ReferenceImportReceipt:
        with self._root.exclusive() as root:
            spec = self._current(operation_id)
            status = self._status(root, operation_id, spec)
            if status.state == "published":
                return status.receipt
            if status.state != "not_found":
                code = "source_import_failed" if status.state == "failed" else "source_import_pending_reconciliation"
                raise WorkspaceFileError(code)
            return self._perform(root, self._record_intent(root, operation_id, spec))

    def query(self, operation_id: str) -> ReferenceImportStatus:
        with self._root.exclusive() as root:
            return self._status(root, operation_id, self._current(operation_id))

    def close(self) -> None:
        self._root.close()
