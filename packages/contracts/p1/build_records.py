"""Immutable build inputs and bounded facts; content verification is not execution."""

from typing import Literal

import rfc8785
from pydantic import Field, StrictBool, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import (
    EngineeringRef, InputSet, UtcTimestamp, expect_kind, input_set_digest,
)
from packages.contracts.p1.build_artifacts import ArtifactContent, ArtifactStorageId, artifact_content_ref
from packages.contracts.p1.build_requests import BuildArtifactRole, BuildDefinition
from packages.contracts.p1.workspace_git import CandidateSnapshot, content_digest


def build_digest(value: Contract) -> str:
    return content_digest(rfc8785.dumps(value.model_dump(mode="json")))


def build_input_references(source: InputSet, candidate: CandidateSnapshot, definition: BuildDefinition):
    definition_digest = build_digest(definition)
    refs = (*source.references, EngineeringRef(
        kind="candidate", object_id=candidate.candidate_id, revision=candidate.candidate_commit,
        authority="workspaces", digest=build_digest(candidate), digest_algorithm="sha256",
    ), EngineeringRef(
        kind="build", object_id="definition-" + definition_digest[7:],
        revision=definition.schema_revision, authority="delivery",
        digest=definition_digest, digest_algorithm="sha256",
    ))
    return refs


class BuildFixedInputs(Contract):
    source_input_set_ref: EngineeringRef
    source_input_set: InputSet
    candidate: CandidateSnapshot
    definition: BuildDefinition
    input_set: InputSet

    @model_validator(mode="after")
    def check_input_set(self):
        expect_kind(self.source_input_set_ref, "input_set")
        if self.source_input_set_ref.object_id != self.source_input_set.input_set_id:
            raise ValueError("build_source_input_set_mismatch")
        refs = build_input_references(self.source_input_set, self.candidate, self.definition)
        if (self.input_set.set_digest != input_set_digest(refs)
                or set(ref.model_dump_json() for ref in self.input_set.references)
                != set(ref.model_dump_json() for ref in refs)):
            raise ValueError("build_input_set_binding_mismatch")
        if self.definition.acceptance_assets_ref not in self.source_input_set.references:
            raise ValueError("build_acceptance_assets_mismatch")
        if len(rfc8785.dumps(self.model_dump(mode="json"))) > 60000:
            raise ValueError("build_inputs_too_large")
        return self


class BuildRunRecord(Contract):
    build_run_id: Identifier
    operation_id: Identifier
    command_id: Identifier
    project_id: Identifier
    task_id: Identifier
    accepted_task_version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    request_digest: Digest
    fixed_inputs: BuildFixedInputs
    build_input_digest: Digest
    accepted_at: UtcTimestamp

    @model_validator(mode="after")
    def check_binding(self):
        candidate = self.fixed_inputs.candidate
        if (candidate.binding.project_id != self.project_id or candidate.binding.task_id != self.task_id
                or self.build_run_id != "build-" + self.command_id
                or self.operation_id != "build-operation-" + self.command_id
                or build_digest(self.fixed_inputs) != self.build_input_digest):
            raise ValueError("build_run_binding_mismatch")
        return self


class BuildArtifactLocator(Contract):
    role: BuildArtifactRole
    storage_id: ArtifactStorageId


class BuildArtifactRecord(BuildArtifactLocator):
    content_ref: EngineeringRef
    archive_digest: Digest
    archive_bytes: int = Field(strict=True, ge=1024, le=2 * 1024**3)
    platform: Literal["linux/amd64"] = "linux/amd64"
    manifest_digest: Digest
    config_digest: Digest
    image_id: Digest

    @model_validator(mode="after")
    def check_identity(self):
        expect_kind(self.content_ref, "artifact")
        if (self.content_ref.authority != "artifacts" or self.content_ref.object_id != self.storage_id
                or self.storage_id != "oci-" + self.archive_digest[7:]
                or self.config_digest != self.image_id):
            raise ValueError("build_artifact_binding_invalid")
        return self


def build_artifact_record(role: str, content: ArtifactContent) -> BuildArtifactRecord:
    return BuildArtifactRecord(
        role=role, storage_id=content.storage_id, content_ref=artifact_content_ref(content),
        archive_digest=content.archive_digest, archive_bytes=content.archive_bytes,
        platform=content.platform, manifest_digest=content.manifest.digest,
        config_digest=content.config.digest, image_id=content.image_id,
    )


class BuildContentRegistration(Contract):
    operation_id: Identifier
    build_input_digest: Digest
    artifacts: tuple[BuildArtifactRecord, ...] = Field(min_length=3, max_length=3)
    observed_at: UtcTimestamp
    applicable: StrictBool

    @model_validator(mode="after")
    def check_names(self):
        if {item.role for item in self.artifacts} != {"frontend", "backend", "postgres"}:
            raise ValueError("build_artifact_roles_incomplete")
        return self


class BuildExecutionArtifact(BuildArtifactLocator):
    """Trusted exporter/loader inspection, separately compared with retained OCI."""

    manifest_digest: Digest
    config_digest: Digest
    loaded_image_id: Digest
    docker_identity_kind: Literal["oci_config", "oci_manifest"] = "oci_config"
    platform: Literal["linux/amd64"] = "linux/amd64"


class BuildExecutionObservation(Contract):
    """Internal trusted-producer protocol, never an HTTP request or a passed flag."""

    observation_id: Identifier
    operation_id: Identifier
    request_digest: Digest
    build_input_digest: Digest
    executor_instance_id: Identifier
    executor_generation: Revision
    previous_observation_id: Identifier | None = None
    closure: Literal["closed_unstarted", "ended_reconciled", "safely_stopped", "running", "unknown"]
    exit_code: int | None = Field(default=None, strict=True, ge=-255, le=255)
    artifacts: tuple[BuildExecutionArtifact, ...] = Field(default=(), max_length=3)
    method_ref: EngineeringRef
    observed_at: UtcTimestamp

    @model_validator(mode="after")
    def check_execution(self):
        expect_kind(self.method_ref, "method")
        if (self.closure == "ended_reconciled") != (self.exit_code is not None):
            raise ValueError("build_exit_code_binding_invalid")
        if self.previous_observation_id == self.observation_id:
            raise ValueError("build_observation_self_supersession")
        if len({item.role for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate_build_artifact_role")
        if self.closure == "ended_reconciled" and self.exit_code == 0 and {
            item.role for item in self.artifacts
        } != {"frontend", "backend", "postgres"}:
            raise ValueError("build_execution_artifacts_incomplete")
        return self


class BuildObservationRegistration(Contract):
    observation: BuildExecutionObservation
    applicable: StrictBool


class BuildView(Contract):
    record: BuildRunRecord
    state: Literal["accepted", "running", "failed", "succeeded", "unknown"]
    content_verified: bool = False
    content: BuildContentRegistration | None = None
    execution: BuildObservationRegistration | None = None
