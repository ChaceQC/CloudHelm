"""Registered physical candidate operations; no authority or final acceptance."""

from typing import Annotated, Literal

import rfc8785
from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.workspace_git import (
    MAX_FILES, MAX_SOURCE_BYTES, CandidateSnapshot, WorkspaceBinding, WorkspaceReadSpec, content_digest,
)

ContainerId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def workspace_runtime_scope_id(binding: WorkspaceBinding) -> str:
    """Stable service registry identity; this is not a freeze or execution grant."""
    return "workspace-runtime-" + content_digest(binding.workspace_id.encode("utf-8"))[7:]


class CandidateFreezeSpec(WorkspaceReadSpec):
    candidate_id: Identifier
    expected_manifest_digest: Digest
    runtime_scope_id: Identifier


def candidate_freeze_digest(spec: CandidateFreezeSpec) -> str:
    return content_digest(rfc8785.dumps({
        "schema_revision": "p1-workspace-candidate-r1", **spec.model_dump(mode="json"),
    }))


class RegisteredWorkspaceReader(Contract):
    """Trusted runtime registration, never a public assertion of read-only access."""

    container_id: ContainerId
    operation_id: Identifier
    scope: Identifier
    method: Identifier
    mount_destination: str = "/workspace"

    @field_validator("mount_destination")
    @classmethod
    def check_destination(cls, value):
        if (not value.startswith("/") or value == "/" or len(value) > 1024
                or any(part in {"", ".", ".."} for part in value.split("/")[1:])
                or any(ord(char) < 32 or char in "\\,:" for char in value)):
            raise ValueError("workspace_reader_destination_invalid")
        return value


class WorkspaceWriterScope(Contract):
    """Restored by a trusted registry under the workspace's exclusive lock."""

    scope_id: Identifier
    binding: WorkspaceBinding
    service_instance_id: Identifier
    service_pid: int = Field(strict=True, ge=1)
    service_start_ticks: Revision
    readers: tuple[RegisteredWorkspaceReader, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def unique_containers(self):
        if len({reader.container_id for reader in self.readers}) != len(self.readers):
            raise ValueError("workspace_reader_duplicate")
        return self


class WorkspaceFreezeProof(Contract):
    method: Literal["p1-workspace-readonly-writers-r1"] = "p1-workspace-readonly-writers-r1"
    runtime_scope_id: Identifier
    writer_scope_digest: Digest
    service_instance_id: Identifier
    service_pid: int = Field(strict=True, ge=1)
    service_start_ticks: Revision
    reader_container_ids: tuple[ContainerId, ...] = Field(max_length=32)
    observed_at: UtcTimestamp


class CandidateFreezeReceipt(Contract):
    schema_revision: Literal["p1-workspace-candidate-r1"] = "p1-workspace-candidate-r1"
    operation_id: Identifier
    request_digest: Digest
    snapshot: CandidateSnapshot
    materialization_operation_id: Identifier
    runtime_scope_id: Identifier
    writer_scope_digest: Digest
    file_count: int = Field(strict=True, ge=0, le=MAX_FILES)
    total_bytes: int = Field(strict=True, ge=0, le=MAX_SOURCE_BYTES)
    observed_at: UtcTimestamp

    @model_validator(mode="after")
    def check_operation(self):
        if self.operation_id != self.snapshot.freeze_operation_id:
            raise ValueError("candidate_operation_mismatch")
        return self


class CandidateFreezeStatus(Contract):
    operation_id: Identifier
    request_digest: Digest
    state: Literal["not_found", "unknown", "captured"]
    receipt: CandidateFreezeReceipt | None = None
    reason_code: str | None = None

    @model_validator(mode="after")
    def check_receipt(self):
        if (self.state == "captured") != (self.receipt is not None):
            raise ValueError("candidate_status_receipt_mismatch")
        if self.receipt is not None and (self.receipt.operation_id != self.operation_id
                                        or self.receipt.request_digest != self.request_digest):
            raise ValueError("candidate_status_identity_mismatch")
        return self
