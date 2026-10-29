"""Bounded inputs and handoff for a verification Agent Run."""

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_git import workspace_path
from packages.contracts.p2.verification import Phase


class VerificationSetup(Contract):
    phase: Phase
    base_url: str
    setup_evidence_ref: EngineeringRef

    @field_validator("base_url")
    @classmethod
    def check_base_url(cls, value: str) -> str:
        match = re.fullmatch(r"http://(?:127\.0\.0\.1|localhost|\[::1\]):([0-9]+)/?", value,
                             re.IGNORECASE | re.ASCII)
        if match is None or not 1 <= int(match.group(1)) <= 65535:
            raise ValueError("verification_base_url_invalid")
        return value

    @model_validator(mode="after")
    def check_setup_evidence(self):
        expect_kind(self.setup_evidence_ref, "evidence")
        return self


class VerificationContext(Contract):
    candidate_id: Identifier
    round_id: Identifier
    setup: VerificationSetup | None = None


class CandidateListDirectory(Contract):
    """List direct children of a fixed candidate directory."""

    path: str = ""
    offset: int = Field(default=0, strict=True, ge=0)
    max_entries: int = Field(default=64, strict=True, ge=1, le=64)

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value, allow_root=True)


class CandidateReadFile(Contract):
    """Read bounded, filtered text from a fixed candidate."""

    path: str
    start_line: int = Field(default=1, strict=True, ge=1)
    start_column: int = Field(default=1, strict=True, ge=1)
    max_lines: int = Field(default=120, strict=True, ge=1, le=160)

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value)


class VerificationRunPhase(Contract):
    phase: Phase


class VerificationFinalize(Contract):
    """Summarize recorded phases into a verification report."""


class VerificationQuery(Contract):
    report_id: Identifier


class VerificationHandoff(Contract):
    """Verifier explanation; a report must be checked against domain facts."""

    reason: Literal["report_ready", "human_decision_required", "continue_required"]
    summary: str = Field(min_length=1, max_length=2048)
    next_action: str = Field(min_length=1, max_length=1024)
    report_id: Identifier | None = None

    @model_validator(mode="after")
    def check_report(self):
        if (self.reason == "report_ready") != (self.report_id is not None):
            raise ValueError("verification_handoff_report_required")
        return self


VERIFICATION_TOOL_SCHEMAS = {
    "candidate.list_directory": CandidateListDirectory,
    "candidate.read_file": CandidateReadFile,
    "verification.run_phase": VerificationRunPhase,
    "verification.finalize": VerificationFinalize,
    "verification.result": VerificationQuery,
}
