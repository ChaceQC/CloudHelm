"""Versioned references and evidence shapes for P0 decisions, without storage."""

import hashlib
from datetime import timedelta
from typing import Annotated, Literal

import rfc8785
from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from packages.contracts.p0.decision_common import (
    Contract, Digest, Identifier, ProtocolRevision, Revision,
)


def _utc(value):
    if value.utcoffset() != timedelta(0):
        raise ValueError("UTC_REQUIRED")
    return value


UtcTimestamp = Annotated[AwareDatetime, AfterValidator(_utc)]
ReferenceKind = Literal[
    "task", "session", "run", "operation", "operation_result", "wait_condition",
    "context", "input_set", "history", "messages", "deferred_results",
    "tool_request", "delivery", "requirement", "contract", "source", "build",
    "artifact", "environment", "environment_config", "parameter_set",
    "resource_binding", "secret_version", "evidence", "acceptance_assets",
    "method", "candidate", "release", "deployment_plan", "deployment_spec",
    "policy", "descriptor", "compose", "runtime", "config_schema",
    "migration", "approval", "variant",
]
IDENTITY_ONLY = frozenset({
    "task", "session", "run", "operation", "wait_condition", "secret_version",
})


class EngineeringRef(Contract):
    kind: ReferenceKind
    object_id: Identifier
    revision: Identifier
    authority: Identifier | None = None
    digest: Digest | None = None
    digest_algorithm: Literal["sha256"] | None = None

    @model_validator(mode="after")
    def check_digest(self):
        if (self.digest is None) != (self.digest_algorithm is None):
            raise ValueError("DIGEST_ALGORITHM_PAIR_REQUIRED")
        if self.kind not in IDENTITY_ONLY and self.digest is None:
            raise ValueError("CONTENT_DIGEST_REQUIRED")
        if self.kind == "secret_version" and self.digest is not None:
            raise ValueError("SECRET_VALUE_DIGEST_FORBIDDEN")
        return self


def expect_kind(ref: EngineeringRef, *kinds: str) -> None:
    if ref.kind not in kinds:
        raise ValueError("REFERENCE_KIND_MISMATCH")


def input_set_digest(refs: tuple[EngineeringRef, ...]) -> str:
    """Sort whole JCS references; order of discovery is not semantic input."""
    encoded = sorted(rfc8785.dumps(ref.model_dump(exclude_none=True)) for ref in refs)
    payload = b"[" + b",".join(encoded) + b"]"
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class InputSet(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    input_set_id: Identifier
    canonicalization: Literal["rfc8785-reference-set-r1"] = "rfc8785-reference-set-r1"
    references: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=128)
    set_digest: Digest

    @model_validator(mode="after")
    def check_set(self):
        identities = {(ref.authority, ref.kind, ref.object_id) for ref in self.references}
        if len(identities) != len(self.references):
            raise ValueError("DUPLICATE_INPUT_IDENTITY")
        if self.set_digest != input_set_digest(self.references):
            raise ValueError("INPUT_SET_DIGEST_MISMATCH")
        return self


class EvidenceRecord(Contract):
    evidence_id: Identifier
    subject_ref: EngineeringRef
    input_set_ref: EngineeringRef
    method_ref: EngineeringRef
    environment_ref: EngineeringRef
    result: Literal["passed", "failed", "unknown", "not_run"]
    observed_at: UtcTimestamp
    support_scope: tuple[Identifier, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.input_set_ref, "input_set")
        expect_kind(self.method_ref, "method", "acceptance_assets")
        expect_kind(self.environment_ref, "environment")
        return self


class DependencyLink(Contract):
    consumer_ref: EngineeringRef
    producer_ref: EngineeringRef
    required_quality: Identifier
    rule_id: Identifier
    rule_version: Identifier


class EvidenceApplicability(Contract):
    evidence_ref: EngineeringRef
    consumer_ref: EngineeringRef
    input_set_ref: EngineeringRef
    input_validity_revision: Revision
    status: Literal["valid", "needs_review", "superseded"]
    rule_id: Identifier
    rule_version: Identifier
    reason_code: Identifier

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.evidence_ref, "evidence")
        expect_kind(self.input_set_ref, "input_set")
        return self


class P0EngineeringContracts(Contract):
    input_set: InputSet
    evidence: EvidenceRecord
    dependency: DependencyLink
    applicability: EvidenceApplicability
