"""Internal, source-bound records consumed by Task; never public write requests."""

import hashlib
from typing import Annotated, Literal

import rfc8785

from pydantic import Field, StrictBool, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import (
    EngineeringRef, EvidenceRecord, InputSet, UtcTimestamp, expect_kind,
)
from packages.contracts.p0.identity_contracts import Principal


class TaskFactSource(Contract):
    project_id: Identifier
    source_id: Identifier
    producer_domain: Literal["projects", "identity", "integration", "execution", "agent-runtime", "collaboration"]
    authority: Identifier
    principal: Principal
    purpose: Literal["product", "protocol_validation"]
    method_ref: EngineeringRef
    executor_ids: tuple[Identifier, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def check_method(self):
        expect_kind(self.method_ref, "method", "acceptance_assets")
        if self.producer_domain == "execution" and not self.executor_ids:
            raise ValueError("execution_source_scope_required")
        return self


class RequirementMetadata(Contract):
    record_kind: Literal["requirement"] = "requirement"
    statement: str = Field(min_length=1, max_length=4096)


class AcceptanceMetadata(Contract):
    record_kind: Literal["acceptance_assets"] = "acceptance_assets"
    required_check_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    method_ref: EngineeringRef

    @model_validator(mode="after")
    def check_checks(self):
        expect_kind(self.method_ref, "method", "acceptance_assets")
        if len(set(self.required_check_ids)) != len(self.required_check_ids):
            raise ValueError("duplicate_required_check")
        return self


class SourceMetadata(Contract):
    record_kind: Literal["source"] = "source"
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class MethodMetadata(Contract):
    record_kind: Literal["method"] = "method"
    description: str = Field(min_length=1, max_length=512)


class EnvironmentMetadata(Contract):
    record_kind: Literal["environment"] = "environment"
    description: str = Field(min_length=1, max_length=512)
    support_scope: tuple[Identifier, ...] = Field(min_length=1, max_length=32)


class ResourcePolicyMetadata(Contract):
    record_kind: Literal["resource_policy"] = "resource_policy"
    resource_scope_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    allowed_capabilities: tuple[Identifier, ...] = Field(min_length=1, max_length=32)


class HumanPolicyMetadata(Contract):
    record_kind: Literal["human_policy"] = "human_policy"
    is_completion_gate: StrictBool
    skip_allowed: StrictBool


class InputSetMetadata(Contract):
    record_kind: Literal["input_set"] = "input_set"
    input_set: InputSet


class CandidateMetadata(Contract):
    record_kind: Literal["candidate"] = "candidate"
    source_ref: EngineeringRef
    input_set_ref: EngineeringRef

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.source_ref, "source")
        expect_kind(self.input_set_ref, "input_set")
        return self


class OperationIntentMetadata(Contract):
    record_kind: Literal["operation"] = "operation"
    owner_kind: Literal["task", "shared", "independent"]
    owner_id: Identifier
    request_digest: Digest
    attempt_id: Identifier
    step_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    executor_id: Identifier
    executor_generation: Revision
    input_set_ref: EngineeringRef

    @model_validator(mode="after")
    def check_input(self):
        expect_kind(self.input_set_ref, "input_set")
        if len(set(self.step_ids)) != len(self.step_ids):
            raise ValueError("duplicate_operation_step")
        return self


class EvidenceMetadata(Contract):
    record_kind: Literal["evidence"] = "evidence"
    evidence: EvidenceRecord
    role: Literal["verification", "work_item_acceptance", "operation_closure", "human_test"]
    check_ids: tuple[Identifier, ...] = Field(default=(), max_length=64)
    acceptance_assets_ref: EngineeringRef | None = None
    work_item_id: Identifier | None = None
    work_item_revision: Revision | None = None
    fact_digest: Digest | None = None

    @model_validator(mode="after")
    def check_scope(self):
        if len(set(self.check_ids)) != len(self.check_ids):
            raise ValueError("duplicate_evidence_check")
        if self.role in {"verification", "work_item_acceptance"}:
            if self.acceptance_assets_ref is None or not self.check_ids:
                raise ValueError("acceptance_evidence_scope_required")
            expect_kind(self.acceptance_assets_ref, "acceptance_assets")
            expect_kind(self.evidence.subject_ref, "candidate")
        work_item_fields = self.work_item_id is not None and self.work_item_revision is not None
        if (self.role == "work_item_acceptance") != work_item_fields:
            raise ValueError("work_item_evidence_binding_required")
        if self.role != "work_item_acceptance" and (self.work_item_id is not None or self.work_item_revision is not None):
            raise ValueError("work_item_evidence_binding_forbidden")
        if self.role == "operation_closure" and self.fact_digest is None:
            raise ValueError("operation_fact_digest_required")
        return self


class HumanConclusionMetadata(Contract):
    record_kind: Literal["human_conclusion"] = "human_conclusion"
    session_id: Identifier
    policy_ref: EngineeringRef
    input_set_ref: EngineeringRef
    conclusion: Literal["passed", "changes_requested", "skipped"]
    concluded_by: Principal
    concluded_at_utc: UtcTimestamp
    evidence_ref: EngineeringRef
    authorization_decision_id: Identifier
    skip_reason: Identifier | None = None

    @model_validator(mode="after")
    def check_human(self):
        expect_kind(self.policy_ref, "policy")
        expect_kind(self.input_set_ref, "input_set")
        expect_kind(self.evidence_ref, "evidence")
        if self.concluded_by.kind != "human":
            raise ValueError("human_conclusion_requires_human")
        if (self.conclusion == "skipped") != (self.skip_reason is not None):
            raise ValueError("human_skip_reason_required_only_for_skip")
        return self


class RunHistoryMetadata(Contract):
    record_kind: Literal["run_history"] = "run_history"
    run_id: Identifier
    run_revision: Revision
    request_boundary_id: Identifier


ReferenceMetadata = Annotated[
    RequirementMetadata | AcceptanceMetadata | SourceMetadata | MethodMetadata | EnvironmentMetadata | ResourcePolicyMetadata
    | HumanPolicyMetadata | InputSetMetadata | CandidateMetadata | OperationIntentMetadata | EvidenceMetadata
    | HumanConclusionMetadata | RunHistoryMetadata,
    Field(discriminator="record_kind"),
]


def operation_scope_digest(
    operation_ref: EngineeringRef, attempt_id: str, step_ids: tuple[str, ...],
    executor_id: str, executor_generation: int, input_set_ref: EngineeringRef,
) -> str:
    value = {
        "profile": "p1-task-operation-scope-r1", "operation_ref": operation_ref.model_dump(mode="json"),
        "attempt_id": attempt_id, "step_ids": step_ids, "executor_id": executor_id,
        "executor_generation": executor_generation, "input_set_ref": input_set_ref.model_dump(mode="json"),
    }
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


class RegisteredReference(Contract):
    project_id: Identifier
    registration_id: Identifier
    source_id: Identifier
    source_record_id: Identifier
    reference: EngineeringRef
    metadata: ReferenceMetadata
    observed_at_utc: UtcTimestamp

    @model_validator(mode="after")
    def check_binding(self):
        kind = self.metadata.record_kind
        expected = {
            "resource_policy": "policy", "human_policy": "policy",
            "human_conclusion": "evidence", "run_history": "history",
        }.get(kind, kind)
        expect_kind(self.reference, expected)
        if self.reference.digest is None:
            raise ValueError("registered_content_digest_required")
        if kind == "source" and self.reference.revision != self.metadata.commit:
            raise ValueError("registered_source_commit_mismatch")
        if kind == "input_set" and self.reference.object_id != self.metadata.input_set.input_set_id:
            raise ValueError("registered_input_set_mismatch")
        if kind == "evidence" and self.reference.object_id != self.metadata.evidence.evidence_id:
            raise ValueError("registered_evidence_identity_mismatch")
        return self


class OperationObservation(Contract):
    """An immutable producer receipt, not the lifecycle of the physical operation."""

    observation_id: Identifier
    project_id: Identifier
    task_id: Identifier
    source_id: Identifier
    source_record_id: Identifier
    operation_ref: EngineeringRef
    attempt_id: Identifier
    step_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    executor_id: Identifier
    executor_generation: Revision
    control_revision: Revision
    input_set_ref: EngineeringRef
    resulting_input_set_ref: EngineeringRef
    effect_scope_digest: Digest
    closure: Literal["closed_unstarted", "ended_reconciled", "safely_stopped", "running", "stop_requested", "unknown"]
    evidence_ref: EngineeringRef
    effects_recorded: StrictBool = False
    supersedes_observation_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    reconciliation_evidence_ref: EngineeringRef | None = None
    observed_at_utc: UtcTimestamp

    @model_validator(mode="after")
    def check_references(self):
        expect_kind(self.operation_ref, "operation")
        expect_kind(self.input_set_ref, "input_set")
        expect_kind(self.resulting_input_set_ref, "input_set")
        expect_kind(self.evidence_ref, "evidence")
        if len(set(self.step_ids)) != len(self.step_ids):
            raise ValueError("duplicate_operation_step")
        if len(set(self.supersedes_observation_ids)) != len(self.supersedes_observation_ids):
            raise ValueError("duplicate_observation_supersession")
        if self.observation_id in self.supersedes_observation_ids:
            raise ValueError("self_supersession_forbidden")
        if bool(self.supersedes_observation_ids) != (self.reconciliation_evidence_ref is not None):
            raise ValueError("explicit_reconciliation_evidence_required")
        if self.reconciliation_evidence_ref is not None:
            expect_kind(self.reconciliation_evidence_ref, "evidence")
        expected = operation_scope_digest(self.operation_ref, self.attempt_id, self.step_ids,
                                          self.executor_id, self.executor_generation, self.input_set_ref)
        if self.effect_scope_digest != expected:
            raise ValueError("operation_scope_digest_mismatch")
        return self


def operation_assertion_digest(receipt: OperationObservation) -> str:
    """Bind the physical assertion without a circular digest through its proof refs."""
    value = receipt.model_dump(mode="json", exclude={"evidence_ref", "reconciliation_evidence_ref"})
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()
