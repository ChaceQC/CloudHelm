"""Bounded Hub records composed from Git DTOs; no execution or acceptance grants."""

import hashlib
from typing import Literal

import rfc8785
from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.workspace_git import (
    CandidateSnapshot, RegisteredGitSource, WorkspaceBinding, WorkspaceFiles,
)

RecordRevision = Literal["p1-workspace-records-r1"]
GitMetadata = RegisteredGitSource | WorkspaceBinding | WorkspaceFiles | CandidateSnapshot


def workspace_metadata_digest(value: GitMetadata) -> str:
    """Hash the exact versioned metadata, independently of Git or manifest digests."""
    if type(value) not in (RegisteredGitSource, WorkspaceBinding, WorkspaceFiles, CandidateSnapshot):
        raise TypeError("workspace_metadata_type_invalid")
    encoded = rfc8785.dumps(value.model_dump(mode="json"))
    limit = 16384 if isinstance(value, (RegisteredGitSource, WorkspaceBinding)) else 32768
    if len(encoded) > limit:
        raise ValueError("workspace_metadata_too_large")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class GitSourceRecord(Contract):
    schema_revision: RecordRevision = "p1-workspace-records-r1"
    source: RegisteredGitSource
    source_digest: Digest
    registered_by_command_id: Identifier
    authorization_decision_id: Identifier
    registered_at: UtcTimestamp

    @model_validator(mode="after")
    def check_digest(self):
        if self.source_digest != workspace_metadata_digest(self.source):
            raise ValueError("git_source_metadata_digest_mismatch")
        return self


class WorkspaceRecord(Contract):
    schema_revision: RecordRevision = "p1-workspace-records-r1"
    binding: WorkspaceBinding
    binding_digest: Digest
    files: WorkspaceFiles | None = None
    files_digest: Digest | None = None
    created_by_command_id: Identifier
    authorization_decision_id: Identifier
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def check_receipt(self):
        if self.binding_digest != workspace_metadata_digest(self.binding):
            raise ValueError("workspace_binding_digest_mismatch")
        if (self.files is None) != (self.files_digest is None):
            raise ValueError("workspace_files_digest_pair_required")
        if self.files is not None:
            # The original byte receipt remains immutable as the mutable binding
            # advances. Its ownership/base identity can never change.
            revisions = {"workspace_revision", "write_generation"}
            if (self.files.binding.model_dump(exclude=revisions) != self.binding.model_dump(exclude=revisions)
                    or self.files.binding.workspace_revision > self.binding.workspace_revision
                    or self.files.binding.write_generation > self.binding.write_generation):
                raise ValueError("workspace_files_binding_mismatch")
            if self.files_digest != workspace_metadata_digest(self.files):
                raise ValueError("workspace_files_digest_mismatch")
        return self


class PhysicalCandidateRecord(Contract):
    schema_revision: RecordRevision = "p1-workspace-records-r1"
    snapshot: CandidateSnapshot
    snapshot_digest: Digest
    created_by_command_id: Identifier
    authorization_decision_id: Identifier
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def check_digest(self):
        if self.snapshot_digest != workspace_metadata_digest(self.snapshot):
            raise ValueError("physical_candidate_digest_mismatch")
        return self
