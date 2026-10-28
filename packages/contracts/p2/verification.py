"""Controlled verification facts and their separate consumer applicability."""

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, EvidenceRecord, InputSet, UtcTimestamp, expect_kind

VERIFICATION_SCHEMA = "p2-verification-r1"
Phase = Literal["baseline", "seed", "verify-persisted", "not-ready"]


class VerificationPhaseRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    candidate_id: Identifier
    round_id: Identifier
    source_id: Identifier
    phase: Phase
    setup_evidence_ref: EngineeringRef

    @model_validator(mode="after")
    def check_setup(self):
        expect_kind(self.setup_evidence_ref, "evidence")
        return self


class VerificationPhase(Contract):
    phase_id: Identifier
    project_id: Identifier
    task_id: Identifier
    candidate_id: Identifier
    round_id: Identifier
    phase: Phase
    setup_evidence_ref: EngineeringRef
    asset_bundle_digest: Digest
    passed_check_ids: tuple[Identifier, ...] = Field(max_length=64)
    failed_check_ids: tuple[Identifier, ...] = Field(max_length=64)
    integrity_errors: tuple[Identifier, ...] = Field(max_length=16)
    exit_code: int | None
    output_digest: Digest | None
    observed_at: UtcTimestamp


class FinalizeVerificationRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    candidate_id: Identifier
    round_id: Identifier
    source_id: Identifier
    phase_ids: tuple[Identifier, ...] = Field(default=(), max_length=4)


class VerificationReport(Contract):
    schema_revision: Literal["p2-verification-r1"] = VERIFICATION_SCHEMA
    report_id: Identifier
    project_id: Identifier
    task_id: Identifier
    candidate_id: Identifier
    build_operation_id: Identifier
    round_id: Identifier
    source_input_set_ref: EngineeringRef
    source_ref: EngineeringRef
    input_set: InputSet
    control_revision: Revision
    input_validity_revision: Revision
    acceptance_assets_ref: EngineeringRef
    asset_bundle_digest: Digest
    expected_check_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    passed_check_ids: tuple[Identifier, ...] = Field(max_length=64)
    failed_check_ids: tuple[Identifier, ...] = Field(max_length=64)
    missing_check_ids: tuple[Identifier, ...] = Field(max_length=64)
    integrity_errors: tuple[Identifier, ...] = Field(max_length=64)
    phases: tuple[VerificationPhase, ...] = Field(max_length=4)
    evidence: EvidenceRecord


class VerificationView(Contract):
    report: VerificationReport
    evidence_ref: EngineeringRef
    applicability: Literal["valid", "needs_review"]
    usable: bool
    reason_code: Identifier


class AcceptVerificationRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    report_id: Identifier


class VerificationSelection(Contract):
    command_id: Identifier
    task_id: Identifier
    version: Revision
    report_id: Identifier


class DependencyImpactRequest(Contract):
    producer_ref: EngineeringRef
    change_ref: EngineeringRef
    reason: Identifier


class DependencyImpactResult(Contract):
    command_id: Identifier
    report_ids: tuple[Identifier, ...] = Field(max_length=128)
    task_ids: tuple[Identifier, ...] = Field(max_length=128)
    producer_ref: EngineeringRef
    change_ref: EngineeringRef
    reason: Identifier
