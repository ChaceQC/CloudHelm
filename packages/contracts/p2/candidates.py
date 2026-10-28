"""Fixed candidate inputs and links to existing engineering facts."""

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import (
    EngineeringRef,
    EvidenceApplicability,
    InputSet,
    UtcTimestamp,
    expect_kind,
)

CANDIDATE_SCHEMA = "p2-fixed-candidate-r1"


class FixCandidateRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    build_operation_id: Identifier
    environment_ref: EngineeringRef

    @model_validator(mode="after")
    def check_environment(self):
        expect_kind(self.environment_ref, "environment")
        return self


class CandidateEvidenceLink(Contract):
    scope: Literal["source_snapshot", "build_execution", "artifact_content"]
    evidence_ref: EngineeringRef
    subject_ref: EngineeringRef

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.evidence_ref, "evidence")
        expect_kind(self.subject_ref, "candidate" if self.scope == "source_snapshot" else "build")
        return self


class FixedCandidateRecord(Contract):
    schema_revision: Literal["p2-fixed-candidate-r1"] = CANDIDATE_SCHEMA
    candidate_id: Identifier
    command_id: Identifier
    project_id: Identifier
    task_id: Identifier
    task_version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    source_input_set_ref: EngineeringRef
    build_operation_id: Identifier
    input_set: InputSet
    environment_ref: EngineeringRef
    evidence: tuple[CandidateEvidenceLink, ...] = Field(min_length=3, max_length=3)
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def check_bindings(self):
        expect_kind(self.source_input_set_ref, "input_set")
        expect_kind(self.environment_ref, "environment")
        if {item.scope for item in self.evidence} != {
            "source_snapshot", "build_execution", "artifact_content",
        }:
            raise ValueError("candidate_evidence_scopes_incomplete")
        if self.environment_ref not in self.input_set.references:
            raise ValueError("candidate_environment_not_in_input_set")
        if self.candidate_id != f"fixed-candidate-{self.command_id}":
            raise ValueError("candidate_id_mismatch")
        return self


class FixCandidateCommandResult(Contract):
    command_id: Identifier
    project_id: Identifier
    task_id: Identifier
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    outcome: Literal["fixed", "rejected"]
    code: Identifier
    candidate_id: Identifier | None = None

    @model_validator(mode="after")
    def check_outcome(self):
        if (self.outcome == "fixed") != (self.candidate_id is not None):
            raise ValueError("candidate_outcome_binding_invalid")
        return self


class FixCandidateHttpResult(Contract):
    status_code: Literal[201, 409, 422]
    body: FixCandidateCommandResult


class FixedCandidateView(Contract):
    record: FixedCandidateRecord
    applicability: tuple[EvidenceApplicability, ...] = Field(min_length=3, max_length=3)
