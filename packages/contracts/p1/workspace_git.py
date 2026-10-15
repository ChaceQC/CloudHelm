"""P1.2 Git identities and initial file receipts; these grant no authority."""

import hashlib
import re
from typing import Annotated, Literal

import rfc8785
from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision

GitObjectId = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
StorageId = Annotated[str, Field(pattern=r"^[a-z]+-[0-9a-f]{64}$")]
MAX_FILES = 4096
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul", *(f"{kind}{n}" for kind in ("com", "lpt") for n in range(1, 10))}


def workspace_path(value: str, *, allow_root: bool = False) -> str:
    """Canonical, portable relative paths; filesystem checks remain mandatory."""
    if value == "" and allow_root:
        return value
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(char in value for char in '\\:<>"|?*')):
        raise ValueError("workspace_path_invalid")
    parts = value.split("/")
    if len(parts) > 32 or any(
        part in {"", ".", ".."} or part.casefold() == ".git"
        or part.endswith((".", " ")) or len(part.encode("utf-8")) > 255
        or part.split(".", 1)[0].casefold() in _WINDOWS_DEVICES for part in parts
    ):
        raise ValueError("workspace_path_invalid")
    return value


def git_branch_ref(value: str) -> str:
    if (not isinstance(value, str) or not 12 <= len(value) <= 200
            or not value.startswith("refs/heads/") or value.endswith(("/", "."))
            or ".." in value or "@{" in value
            or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", value)
            or any(not part or part.startswith(".") or part.endswith(".lock")
                   for part in value.split("/"))):
        raise ValueError("git_target_branch_invalid")
    return value


class RegisteredGitSource(Contract):
    schema_revision: Literal["p1-workspace-git-r1"] = "p1-workspace-git-r1"
    project_id: Identifier
    source_id: Identifier
    source_revision: Revision
    kind: Literal["managed_bare", "external"]
    target_branch: str = Field(min_length=12, max_length=200)
    source_prefix: str = ""
    object_format: Literal["sha1", "sha256"]
    access_mode: Literal["read_only", "read_write"]

    @field_validator("source_prefix")
    @classmethod
    def check_prefix(cls, value: str) -> str:
        return workspace_path(value, allow_root=True)

    @field_validator("target_branch")
    @classmethod
    def check_branch(cls, value: str) -> str:
        return git_branch_ref(value)


class WorkspaceBinding(Contract):
    workspace_id: Identifier
    project_id: Identifier
    task_id: Identifier
    work_item_id: Identifier
    owner_user_id: Identifier
    source_id: Identifier
    source_revision: Revision
    base_commit: GitObjectId
    workspace_revision: Revision
    write_generation: Revision


class WorkspaceFiles(Contract):
    """Immutable receipt for the initial bytes, not current mutable view evidence."""

    binding: WorkspaceBinding
    operation_id: Identifier
    storage_id: StorageId
    manifest_digest: Digest
    file_count: int = Field(strict=True, ge=0, le=MAX_FILES)
    total_bytes: int = Field(strict=True, ge=0, le=MAX_SOURCE_BYTES)


class CandidateSnapshot(Contract):
    binding: WorkspaceBinding
    candidate_id: Identifier
    candidate_commit: GitObjectId
    parent_commit: GitObjectId
    freeze_operation_id: Identifier
    storage_id: StorageId
    manifest_digest: Digest

    @model_validator(mode="after")
    def check_object_format(self):
        if len({len(self.binding.base_commit), len(self.candidate_commit), len(self.parent_commit)}) != 1:
            raise ValueError("git_object_format_mismatch")
        return self


class WorkspaceFile(Contract):
    path: str
    mode: Literal["100644", "100755"]
    size_bytes: int = Field(strict=True, ge=0, le=MAX_FILE_BYTES)
    content_digest: Digest

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value)


class GitFile(WorkspaceFile):
    blob_id: GitObjectId


def _check_file_paths(files: tuple[WorkspaceFile, ...]) -> None:
    seen, directories = set(), set()
    for item in files:
        path = item.path.casefold()
        parents = {path[:index] for index, char in enumerate(path) if char == "/"}
        if path in seen or path in directories or parents.intersection(seen):
            raise ValueError("duplicate_source_path")
        seen.add(path)
        directories.update(parents)
    if sum(item.size_bytes for item in files) > MAX_SOURCE_BYTES:
        raise ValueError("source_bytes_exceeded")


class WorkspaceManifest(Contract):
    schema_revision: Literal["p1-workspace-manifest-r1"] = "p1-workspace-manifest-r1"
    files: tuple[WorkspaceFile, ...] = Field(max_length=MAX_FILES)

    @model_validator(mode="after")
    def check_files(self):
        _check_file_paths(self.files)
        return self


def manifest_bytes(files: tuple[WorkspaceFile, ...]) -> bytes:
    entries = [item.model_dump(exclude={"blob_id"}) for item in files]
    entries.sort(key=lambda item: item["path"].encode("utf-8"))
    return rfc8785.dumps({"schema_revision": "p1-workspace-manifest-r1", "files": entries})


def content_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class SourceTree(Contract):
    source: RegisteredGitSource
    commit: GitObjectId
    tree_id: GitObjectId
    files: tuple[GitFile, ...] = Field(max_length=MAX_FILES)
    manifest_digest: Digest

    @model_validator(mode="after")
    def check_tree(self):
        expected = 40 if self.source.object_format == "sha1" else 64
        if any(len(oid) != expected for oid in (self.commit, self.tree_id, *(f.blob_id for f in self.files))):
            raise ValueError("git_object_format_mismatch")
        _check_file_paths(self.files)
        if self.manifest_digest != content_digest(manifest_bytes(self.files)):
            raise ValueError("source_manifest_mismatch")
        return self

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)
