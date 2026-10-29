"""Bounded inputs and handoff for a review Agent Run."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.workspace_git import workspace_path
from packages.contracts.p2.verification_agent import CandidateListDirectory, CandidateReadFile


class ReviewContext(Contract):
    candidate_id: Identifier
    verification_report_id: Identifier | None = None


class CandidateDiff(Contract):
    """Read a bounded diff for a fixed candidate."""

    path: str = ""
    offset: int = Field(default=0, strict=True, ge=0)
    max_entries: int = Field(default=16, strict=True, ge=1, le=16)

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value, allow_root=True)


class ReviewEvidence(Contract):
    """Read server-bound build and verification facts for a fixed candidate."""


class ReviewFinding(Contract):
    path: str
    line: int = Field(strict=True, ge=1)
    severity: Literal["blocking", "advisory"]
    title: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2048)
    evidence_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=8)

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value)


class ReviewHandoff(Contract):
    """Reviewer feedback; the server decides applicability from domain facts."""

    reason: Literal["feedback_ready", "human_decision_required", "continue_required"]
    summary: str = Field(min_length=1, max_length=2048)
    next_action: str = Field(min_length=1, max_length=1024)
    findings: tuple[ReviewFinding, ...] = Field(default=(), max_length=16)
    uncovered: tuple[Annotated[str, Field(max_length=1024)], ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def check_size(self):
        if len(self.model_dump_json().encode("utf-8")) > 8192:
            raise ValueError("review_feedback_too_large")
        return self


REVIEW_TOOL_SCHEMAS = {
    "candidate.list_directory": CandidateListDirectory,
    "candidate.read_file": CandidateReadFile,
    "candidate.diff": CandidateDiff,
    "review.evidence": ReviewEvidence,
}
