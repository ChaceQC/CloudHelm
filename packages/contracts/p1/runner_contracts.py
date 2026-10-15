"""Maintenance-only Runner capability contracts; no product execution admission."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

import rfc8785
from pydantic import Field, computed_field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind

CapabilityName = Literal[
    "rootless_uid", "pid_proc_isolation", "process_sandbox", "group_cpu",
    "group_memory", "group_pids", "tmpfs_limit", "network_isolation",
    "filesystem_boundary", "stop_confirmation",
]
CAPABILITY_NAMES = (
    "rootless_uid", "pid_proc_isolation", "process_sandbox", "group_cpu",
    "group_memory", "group_pids", "tmpfs_limit", "network_isolation",
    "filesystem_boundary", "stop_confirmation",
)
BoundedText = Annotated[str, Field(max_length=600)]


class RunnerOperationSpec(Contract):
    protocol_revision: Literal["p1-runner-probe-r1"] = "p1-runner-probe-r1"
    action: Literal["probe_capabilities"] = "probe_capabilities"
    operation_id: Identifier
    request_digest: Digest
    executor_instance_id: Identifier
    input_set_ref: EngineeringRef
    toolchain_ref: EngineeringRef
    policy_ref: EngineeringRef
    development_envelope_ref: EngineeringRef
    deadline: UtcTimestamp
    project_id: Identifier | None = None
    task_id: Identifier | None = None
    workspace_ref: EngineeringRef | None = None
    candidate_ref: EngineeringRef | None = None
    expected_workspace_revision: Revision | None = None
    writer_generation: Revision | None = None

    @model_validator(mode="after")
    def validate_registered_probe(self):
        if any((self.project_id, self.task_id, self.workspace_ref, self.candidate_ref,
                self.expected_workspace_revision is not None, self.writer_generation is not None)):
            raise ValueError("maintenance_probe_cannot_target_business_objects")
        expect_kind(self.input_set_ref, "input_set")
        expect_kind(self.toolchain_ref, "artifact")
        expect_kind(self.policy_ref, "policy")
        expect_kind(self.development_envelope_ref, "policy")
        if self.request_digest != operation_digest(self):
            raise ValueError("runner_operation_digest_mismatch")
        return self


def operation_digest(spec: RunnerOperationSpec) -> str:
    payload = spec.model_dump(mode="json", exclude={"request_digest"})
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


class CapabilityEvidence(Contract):
    capability: CapabilityName
    status: Literal["verified", "unsupported", "unverified"]
    reason: Identifier
    observations: tuple[BoundedText, ...] = Field(default=(), max_length=16)


class RunnerCapabilityReport(Contract):
    method_revision: Literal["p1-runner-capabilities-r1"] = "p1-runner-capabilities-r1"
    spec: RunnerOperationSpec
    started_at: UtcTimestamp
    finished_at: UtcTimestamp
    toolchain_image_id: Digest | None = None
    container_id: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    probe_input_digest: Digest | None = None
    security_exceptions: tuple[Identifier, ...] = Field(max_length=8)
    capabilities: tuple[CapabilityEvidence, ...] = Field(min_length=10, max_length=10)
    failures: tuple[Identifier, ...] = Field(default=(), max_length=16)
    diagnostics: tuple[BoundedText, ...] = Field(default=(), max_length=16)
    support_scope: Literal["controlled_wsl_offline_tmpfs_probe_only"] = (
        "controlled_wsl_offline_tmpfs_probe_only"
    )

    @model_validator(mode="after")
    def require_each_capability(self):
        if {entry.capability for entry in self.capabilities} != set(CAPABILITY_NAMES):
            raise ValueError("runner_capability_set_incomplete")
        if self.finished_at < self.started_at:
            raise ValueError("runner_observation_time_reversed")
        return self

    @computed_field
    @property
    def all_required_verified(self) -> bool:
        return not self.failures and all(entry.status == "verified" for entry in self.capabilities)
