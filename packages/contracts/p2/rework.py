"""Bounded requests and immutable feedback facts for a development work item."""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_git import GitObjectId

REWORK_SCHEMA = "p2-rework-r1"


class ReceiveReworkRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    source_run_id: Identifier | None = None
    verification_report_id: Identifier | None = None

    @model_validator(mode="after")
    def check_source(self):
        if (self.source_run_id is None) == (self.verification_report_id is None):
            raise ValueError("rework_exactly_one_source_required")
        return self


class ResolveReworkRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    issue_id: Identifier
    verification_report_id: Identifier
    review_run_id: Identifier | None = None


class ReworkIssue(Contract):
    schema_revision: Literal["p2-rework-r1"] = REWORK_SCHEMA
    issue_id: Identifier
    task_id: Identifier
    work_item_id: Identifier
    owner_session_id: Identifier | None
    source_kind: Literal["review", "verification"]
    source_id: Identifier
    candidate_id: Identifier
    candidate_commit: GitObjectId
    source_input_set_ref: EngineeringRef
    evidence_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=8)
    fingerprint: Digest
    title: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=16384)
    severity: Literal["blocking", "advisory"]
    path: str | None = None
    line: int | None = Field(default=None, strict=True, ge=1)
    check_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    previous_issue_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    control_revision: Revision
    input_validity_revision: Revision

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.source_input_set_ref, "input_set")
        for ref in self.evidence_refs:
            expect_kind(ref, "evidence")
        return self


class ReworkReceipt(Contract):
    command_id: Identifier
    task_id: Identifier
    version: Revision
    source_id: Identifier
    issue_ids: tuple[Identifier, ...] = Field(max_length=128)
    work_item_id: Identifier
    owner_session_id: Identifier | None


class ReworkResolutionReceipt(Contract):
    command_id: Identifier
    task_id: Identifier
    version: Revision
    issue_id: Identifier
    resolution: dict[str, JsonValue]


class ReworkResolutionEvent(Contract):
    issue_id: Identifier
    resolution: dict[str, JsonValue]
