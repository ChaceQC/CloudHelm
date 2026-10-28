"""Project FIFO integration, exact final inputs and independent review."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp
from packages.contracts.p0.identity_contracts import Principal
from packages.contracts.p1.workspace_git import CandidateSnapshot, GitObjectId, RegisteredGitSource

MERGE_SCHEMA = "p2-project-merge-r1"


class MergeTaskRevision(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision


class EnqueueMergeRequest(MergeTaskRevision):
    candidate_id: Identifier


class AdvanceMergeRequest(MergeTaskRevision):
    attempt_id: Identifier
    action: Literal["merge", "retry", "withdraw", "reconcile"]
    verification_report_id: Identifier | None = None


class ReviewMergeRequest(MergeTaskRevision):
    attempt_id: Identifier
    verification_report_id: Identifier
    conclusion: Literal["approved", "changes_requested"]
    reason: str = Field(min_length=1, max_length=1024)


class MergeQueueEntry(Contract):
    entry_id: Identifier
    command_id: Identifier
    project_id: Identifier
    task_id: Identifier
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    source_input_set_ref: EngineeringRef
    source: RegisteredGitSource
    candidate: CandidateSnapshot
    state: Literal["queued", "preparing", "awaiting_evidence", "applying", "merged", "conflict", "withdrawn"]
    attempt_id: Identifier
    review_id: Identifier | None = None
    verification_report_id: Identifier | None = None
    apply_command_id: Identifier | None = None
    created_at: UtcTimestamp


class IntegrationAttempt(Contract):
    attempt_id: Identifier
    entry_id: Identifier
    project_id: Identifier
    task_id: Identifier
    base_commit: GitObjectId
    candidate_commit: GitObjectId
    state: Literal["prepared", "conflict"]
    snapshot: CandidateSnapshot | None = None
    conflict_paths: tuple[str, ...] = Field(default=(), max_length=128)
    conflict_paths_truncated: bool = False
    reason_code: Identifier | None = None


class IntegrationReview(Contract):
    review_id: Identifier
    entry_id: Identifier
    attempt_id: Identifier
    integrated_commit: GitObjectId
    input_set_ref: EngineeringRef
    verification_report_id: Identifier
    conclusion: Literal["approved", "changes_requested"]
    reason: str = Field(min_length=1, max_length=1024)
    reviewed_by: Principal
    authorization_decision_id: Identifier
    reviewed_at: UtcTimestamp


class MergeQueueView(Contract):
    entry: MergeQueueEntry
    attempt: IntegrationAttempt | None = None
    review: IntegrationReview | None = None
