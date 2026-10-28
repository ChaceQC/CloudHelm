"""Workspace ownership handoff requests and persisted results."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.workspace_candidates import CandidateFreezeReceipt, CandidateFreezeSpec
from packages.contracts.p1.workspace_git import WorkspaceChange
from packages.contracts.p1.workspace_requests import WorkspaceVersionGuard


class WorkspaceHandoffRequest(WorkspaceVersionGuard):
    action: Literal["takeover", "return"]
    expected_manifest_digest: Digest
    reason: str = Field(min_length=1, max_length=1024)
    handoff_id: Identifier | None = None

    @field_validator("reason")
    @classmethod
    def check_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace_handoff_reason_required")
        return value

    @model_validator(mode="after")
    def check_handoff_id(self):
        if (self.action == "return") != (self.handoff_id is not None):
            raise ValueError("workspace_handoff_id_invalid")
        return self


class WorkspaceHandoffRecord(Contract):
    handoff_id: Identifier
    workspace_id: Identifier
    task_id: Identifier
    human_user_id: Identifier
    reason: str
    state: Literal["handoff_pending", "human_owned", "return_pending", "agent_owned"]
    takeover_spec: CandidateFreezeSpec
    return_spec: CandidateFreezeSpec | None = None
    baseline: CandidateFreezeReceipt | None = None
    returned: CandidateFreezeReceipt | None = None
    changes: tuple[WorkspaceChange, ...] = ()
    created_at: UtcTimestamp


class WorkspaceHandoffResult(Contract):
    command_id: Identifier
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    handoff: WorkspaceHandoffRecord
