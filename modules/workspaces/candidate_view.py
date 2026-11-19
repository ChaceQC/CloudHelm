"""Read exact candidate metadata and fetch only the selected raw blobs."""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from uuid import uuid4

from modules.workspaces.git_objects import (
    _OPERATION_SECONDS, GitObjectStore, GitTreeEntry, _object_id, _read_object, read_commit_entries,
)
from modules.workspaces.safe_paths import WorkspaceFileError, directory_at, exists_at, read_regular, write_new_file
from packages.contracts.p1.workspace_git import (
    MAX_FILE_BYTES, CandidateSnapshot, GitFile, RegisteredGitSource, WorkspaceFile, WorkspaceManifest,
    content_digest, manifest_bytes,
)

_MANIFEST_DIRECTORY = "candidate-manifests"
_MANIFEST_LIMIT = 8 * 1024 * 1024


def retain_candidate_manifest(directory: int, files: tuple[WorkspaceFile, ...]) -> str:
    """Publish under the caller's repository lock before exposing the snapshot."""
    raw = manifest_bytes(files)
    digest = content_digest(raw)
    name = f"{digest[7:]}.json"
    with directory_at(directory, _MANIFEST_DIRECTORY, create=True) as manifests:
        if exists_at(manifests, name):
            if read_regular(manifests, name, _MANIFEST_LIMIT) != raw:
                raise WorkspaceFileError("candidate_manifest_mismatch")
        else:
            staged = "stage-" + uuid4().hex
            try:
                write_new_file(manifests, staged, raw)
                os.rename(staged, name, src_dir_fd=manifests, dst_dir_fd=manifests)
                os.fsync(manifests)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(staged, dir_fd=manifests)
    return digest


@dataclass(slots=True)
class CandidateView:
    files: dict[str, GitFile]
    baseline: dict[str, GitTreeEntry]
    _directory: int
    _deadline: float

    def _read_blob(self, oid: str, limit: int) -> bytes:
        if self._directory < 0:
            raise WorkspaceFileError("git_file_scope_mismatch")
        return _read_object(self._directory, "blob", oid, min(limit, MAX_FILE_BYTES), self._deadline)

    def read_file(self, path: str, limit: int) -> bytes:
        entry = self.files.get(path)
        if entry is None:
            raise WorkspaceFileError("git_file_scope_mismatch")
        if entry.size_bytes > limit:
            raise WorkspaceFileError("git_output_limit_exceeded")
        data = self._read_blob(entry.blob_id, limit)
        if len(data) != entry.size_bytes or content_digest(data) != entry.content_digest:
            raise WorkspaceFileError("git_file_digest_mismatch")
        return data

    def read_baseline(self, path: str, limit: int) -> bytes | None:
        entry = self.baseline.get(path)
        if entry is None:
            raise WorkspaceFileError("git_file_scope_mismatch")
        try:
            return self._read_blob(entry.blob_id, limit)
        except WorkspaceFileError as error:
            if error.code == "git_output_limit_exceeded":
                return None
            raise


@contextmanager
def open_candidate_view(
    git: GitObjectStore, source: RegisteredGitSource, snapshot: CandidateSnapshot, *, include_baseline: bool = False,
) -> Iterator[CandidateView]:
    binding = snapshot.binding
    if (binding.project_id, binding.source_id, binding.source_revision) != (
        source.project_id, source.source_id, source.source_revision,
    ):
        raise WorkspaceFileError("candidate_source_binding_mismatch")
    commit = _object_id(snapshot.candidate_commit, source.object_format)
    parent = _object_id(snapshot.parent_commit, source.object_format)
    with git.integration_repository(source) as directory:
        deadline = time.monotonic() + _OPERATION_SECONDS
        raw = read_regular(directory, f"{_MANIFEST_DIRECTORY}/{snapshot.manifest_digest[7:]}.json", _MANIFEST_LIMIT)
        if content_digest(raw) != snapshot.manifest_digest:
            raise WorkspaceFileError("candidate_manifest_mismatch")
        try:
            manifest = WorkspaceManifest.model_validate_json(raw)
        except ValueError:
            raise WorkspaceFileError("candidate_manifest_invalid") from None
        if manifest_bytes(manifest.files) != raw:
            raise WorkspaceFileError("candidate_manifest_invalid")

        tree = read_commit_entries(directory, commit, source.source_prefix, deadline, expected_parent=parent)
        if len(tree) != len(manifest.files):
            raise WorkspaceFileError("candidate_git_manifest_mismatch")
        files = {}
        for item in manifest.files:
            entry = tree.get(item.path)
            if entry is None or entry.mode != item.mode:
                raise WorkspaceFileError("candidate_git_manifest_mismatch")
            files[item.path] = GitFile.model_construct(**item.model_dump(), blob_id=entry.blob_id)
        baseline = read_commit_entries(directory, parent, source.source_prefix, deadline) if include_baseline else {}
        view = CandidateView(files, baseline, directory, deadline)
        try:
            yield view
        finally:
            view._directory = -1
