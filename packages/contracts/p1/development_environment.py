"""Fixed local artifact-verification inputs and observations, without business approval."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

import rfc8785
from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind
from packages.contracts.p1.build_artifacts import ArtifactContent
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.workspace_git import WorkspaceBinding

DATA_REVISION = "reference-synthetic-r1"
MIGRATION_REVISION = "0002_add_updated_at_index"
POSTGRES_REFERENCE = "postgres:16.13@sha256:5d143123fdf80462d1778cd4f24b9f7ca13c87174bca19141fb194c5a1ebca59"
POSTGRES_MANIFEST = "sha256:3102b2114b39383b61fa194e5929734c72a56ce366dbb391509b1f07aef10f9f"
ROLES = ("postgres", "backend", "frontend")
EnvironmentState = Literal["preparing", "ready", "suspended", "failed", "disposed"]


class ArtifactEnvironmentSpec(Contract):
    schema_revision: Literal["p1-artifact-environment-r1"] = "p1-artifact-environment-r1"
    operation_id: Annotated[str, Field(pattern=r"^artifact-env-[0-9a-f]{32}$")]
    source_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")]
    input_set_ref: EngineeringRef
    storage_ref: DevelopmentStorageRef
    data_revision: Literal["reference-synthetic-r1"] = DATA_REVISION
    migration_revision: Literal["0002_add_updated_at_index"] = MIGRATION_REVISION
    acceptance_bundle_digest: Digest
    deadline: UtcTimestamp

    @model_validator(mode="after")
    def fixed_scope(self):
        expect_kind(self.input_set_ref, "input_set")
        if self.storage_ref.purpose != "workspace":
            raise ValueError("artifact_environment_requires_workspace_storage")
        return self


class EnvironmentArtifactSet(Contract):
    postgres: ArtifactContent
    backend: ArtifactContent
    frontend: ArtifactContent

    @model_validator(mode="after")
    def separate_roles(self):
        if len({getattr(self, role).image_id for role in ROLES}) != 3:
            raise ValueError("artifact_environment_role_identity_collision")
        return self


class ArtifactEnvironmentObservation(Contract):
    spec: ArtifactEnvironmentSpec
    state: EnvironmentState
    observed_at: UtcTimestamp
    data_generation: Annotated[int, Field(strict=True, ge=0)]
    artifacts: EnvironmentArtifactSet | None = None
    entrance: Annotated[str, Field(pattern=r"^http://127\.0\.0\.1:[0-9]{1,5}$")] | None = None
    running_roles: tuple[Literal["postgres", "backend", "frontend"], ...] = ()
    migration_observed: Literal["0002_add_updated_at_index"] | None = None
    process_and_readiness_verified: bool = False
    retained_storage_accounting: Literal["whole_bounded_backing_remains_charged"] = (
        "whole_bounded_backing_remains_charged"
    )
    human_acceptance: None = None

    @model_validator(mode="after")
    def observed_state(self):
        if len(set(self.running_roles)) != len(self.running_roles):
            raise ValueError("artifact_environment_duplicate_running_role")
        if self.state == "ready" and (
            self.artifacts is None or set(self.running_roles) != set(ROLES)
            or self.entrance is None or self.migration_observed is None
            or not self.process_and_readiness_verified or self.data_generation < 1
        ):
            raise ValueError("artifact_environment_ready_requires_physical_evidence")
        if self.state in {"suspended", "disposed"} and (
            self.running_roles or self.entrance is not None or self.process_and_readiness_verified
        ):
            raise ValueError("artifact_environment_stopped_state_has_live_resources")
        return self


# Mutable Workspace development environments are a separate lifecycle from the
# fixed-input artifact environment above. Requests describe bounded intent only;
# process, readiness, and stop facts enter through the authenticated Runner path.
WorkspaceDevelopmentState = Literal["preparing", "ready", "suspended", "failed", "disposed"]
WorkspaceDevelopmentAction = Literal["prepare", "suspend", "resume", "reset_data", "dispose"]
DevelopmentEnvironmentId = Annotated[str, Field(pattern=r"^dev-env-[0-9a-f]{32}$")]
DevelopmentCommandId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
DevelopmentOperationId = Annotated[
    str, Field(pattern=r"^workspace-dev-env-(prepare|suspend|resume|reset_data|dispose)-[0-9a-f]{32}$")
]
DataRevision = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]

WORKSPACE_DEVELOPMENT_PROFILE = "notes-backend-dev-r1"
WORKSPACE_DEVELOPMENT_PROBE_REVISION = "notes-backend-probes-r1"


def _operation_id(action: str, command_id: str) -> str:
    return f"workspace-dev-env-{action}-{command_id}"


class WorkspaceDevelopmentToolchain(Contract):
    """Pinned toolchain identity selected for the one supported dev profile."""

    artifact_ref: EngineeringRef
    artifact_digest: Digest

    @model_validator(mode="after")
    def check_artifact(self):
        expect_kind(self.artifact_ref, "artifact")
        return self


class WorkspaceDevelopmentEnvironmentSpec(Contract):
    """Fixed service profile and immutable inputs for one mutable Workspace env."""

    schema_revision: Literal["p1-workspace-development-environment-r1"] = (
        "p1-workspace-development-environment-r1"
    )
    environment_id: DevelopmentEnvironmentId
    binding: WorkspaceBinding
    storage_ref: DevelopmentStorageRef
    profile_revision: Literal["notes-backend-dev-r1"] = WORKSPACE_DEVELOPMENT_PROFILE
    toolchain: WorkspaceDevelopmentToolchain
    source_manifest_digest: Digest
    original_lock_digest: Digest
    dependency_cache_key: Digest
    migration_revision: DataRevision
    data_revision: DataRevision
    data_generation: Revision = 0
    source_mount: Literal["workspace_read_only_dynamic"] = "workspace_read_only_dynamic"
    file_mutation_authority: Literal["controlled_workspace_service"] = "controlled_workspace_service"

    @model_validator(mode="after")
    def check_fixed_scope(self):
        if self.storage_ref.purpose != "workspace":
            raise ValueError("workspace_development_requires_workspace_storage")
        return self


class _EnvironmentOperationRequest(Contract):
    command_id: DevelopmentCommandId
    operation_id: DevelopmentOperationId
    environment_id: DevelopmentEnvironmentId
    binding: WorkspaceBinding
    source_manifest_digest: Digest

    def check_identity(self):
        if self.operation_id != _operation_id(self.action, self.command_id):
            raise ValueError("workspace_development_operation_identity_mismatch")
        return self


class PrepareWorkspaceDevelopmentEnvironment(_EnvironmentOperationRequest):
    action: Literal["prepare"] = "prepare"
    expected_environment_revision: Literal[0] = 0
    spec: WorkspaceDevelopmentEnvironmentSpec

    @model_validator(mode="after")
    def check_prepare_binding(self):
        self.check_identity()
        if (self.environment_id != "dev-env-" + self.command_id
                or self.spec.environment_id != self.environment_id
                or self.spec.binding != self.binding
                or self.spec.source_manifest_digest != self.source_manifest_digest):
            raise ValueError("workspace_development_prepare_binding_mismatch")
        return self


class SuspendWorkspaceDevelopmentEnvironment(_EnvironmentOperationRequest):
    action: Literal["suspend"] = "suspend"
    expected_environment_revision: Revision
    expected_data_revision: DataRevision
    expected_data_generation: Revision

    @model_validator(mode="after")
    def check_identity_fields(self):
        return self.check_identity()


class ResumeWorkspaceDevelopmentEnvironment(_EnvironmentOperationRequest):
    action: Literal["resume"] = "resume"
    expected_environment_revision: Revision
    expected_data_revision: DataRevision
    expected_data_generation: Revision
    spec: WorkspaceDevelopmentEnvironmentSpec

    @model_validator(mode="after")
    def check_resume_binding(self):
        self.check_identity()
        if (self.spec.environment_id != self.environment_id or self.spec.binding != self.binding
                or self.spec.source_manifest_digest != self.source_manifest_digest
                or self.spec.data_revision != self.expected_data_revision
                or self.spec.data_generation != self.expected_data_generation):
            raise ValueError("workspace_development_resume_spec_mismatch")
        return self


class ResetWorkspaceDevelopmentData(_EnvironmentOperationRequest):
    action: Literal["reset_data"] = "reset_data"
    expected_environment_revision: Revision
    expected_data_revision: DataRevision
    expected_data_generation: Revision
    target_data_revision: DataRevision

    @model_validator(mode="after")
    def check_identity_fields(self):
        return self.check_identity()


class DisposeWorkspaceDevelopmentEnvironment(_EnvironmentOperationRequest):
    action: Literal["dispose"] = "dispose"
    expected_environment_revision: Revision
    expected_data_revision: DataRevision
    expected_data_generation: Revision

    @model_validator(mode="after")
    def check_identity_fields(self):
        return self.check_identity()


WorkspaceDevelopmentEnvironmentRequest = Annotated[
    PrepareWorkspaceDevelopmentEnvironment
    | SuspendWorkspaceDevelopmentEnvironment
    | ResumeWorkspaceDevelopmentEnvironment
    | ResetWorkspaceDevelopmentData
    | DisposeWorkspaceDevelopmentEnvironment,
    Field(discriminator="action"),
]


def workspace_development_operation_digest(request: WorkspaceDevelopmentEnvironmentRequest) -> str:
    payload = request.model_dump(mode="json")
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


class WorkspaceDevelopmentEnvironmentOperationIntent(Contract):
    """Durable, idempotent intent; it contains no claimed execution outcome."""

    request: WorkspaceDevelopmentEnvironmentRequest
    request_digest: Digest
    accepted_environment_revision: Revision

    @model_validator(mode="after")
    def check_intent(self):
        expected_revision = getattr(self.request, "expected_environment_revision") + 1
        if (self.request_digest != workspace_development_operation_digest(self.request)
                or self.accepted_environment_revision != expected_revision):
            raise ValueError("workspace_development_operation_intent_mismatch")
        return self


class WorkspaceDevelopmentRunnerIdentity(Contract):
    """Identity attached after the Runner channel authenticates its sender."""

    trust_source: Literal["authenticated_dev_runner"] = "authenticated_dev_runner"
    runner_id: Identifier
    runner_generation: Revision
    observation_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    observation_digest: Digest
    observed_at: UtcTimestamp


class WorkspaceDevelopmentRuntimeFact(Contract):
    status: Literal["running", "stopped", "unknown"]
    process_id: Identifier | None
    runner: WorkspaceDevelopmentRunnerIdentity
    binding: WorkspaceBinding
    source_manifest_digest: Digest

    @model_validator(mode="after")
    def check_process_identity(self):
        if (self.status == "running") != (self.process_id is not None):
            raise ValueError("workspace_development_runtime_process_mismatch")
        return self


class WorkspaceDevelopmentProbeFact(Contract):
    probe_revision: Literal["notes-backend-probes-r1"] = WORKSPACE_DEVELOPMENT_PROBE_REVISION
    path: Literal["/health", "/ready"]
    outcome: Literal["passed", "failed", "unknown"]
    response_digest: Digest
    process_id: Identifier
    runner: WorkspaceDevelopmentRunnerIdentity
    binding: WorkspaceBinding
    source_manifest_digest: Digest
    observed_migration_revision: DataRevision | None = None


class WorkspaceDevelopmentStopFact(Contract):
    outcome: Literal["confirmed_stopped", "still_running", "unknown"]
    process_id: Identifier | None
    runner: WorkspaceDevelopmentRunnerIdentity
    binding: WorkspaceBinding


class WorkspaceDevelopmentEnvironmentObservation(Contract):
    """Authenticated Runner facts; never accepted as fields on a user request."""

    schema_revision: Literal["p1-workspace-development-observation-r1"] = (
        "p1-workspace-development-observation-r1"
    )
    environment_id: DevelopmentEnvironmentId
    operation_id: DevelopmentOperationId
    request_digest: Digest
    profile_revision: Literal["notes-backend-dev-r1"] = WORKSPACE_DEVELOPMENT_PROFILE
    binding: WorkspaceBinding
    storage_ref: DevelopmentStorageRef
    source_manifest_digest: Digest
    migration_revision: DataRevision
    data_revision: DataRevision
    data_generation: Revision
    state: WorkspaceDevelopmentState
    runtime_fact: WorkspaceDevelopmentRuntimeFact | None = None
    health_probe: WorkspaceDevelopmentProbeFact | None = None
    ready_probe: WorkspaceDevelopmentProbeFact | None = None
    stop_fact: WorkspaceDevelopmentStopFact | None = None
    failure_code: Identifier | None = None

    @model_validator(mode="after")
    def check_controlled_facts(self):
        if self.storage_ref.purpose != "workspace":
            raise ValueError("workspace_development_observation_storage_mismatch")
        for probe, path in ((self.health_probe, "/health"), (self.ready_probe, "/ready")):
            if probe is not None and (
                probe.path != path or probe.binding != self.binding
                or probe.source_manifest_digest != self.source_manifest_digest
            ):
                raise ValueError("workspace_development_probe_binding_mismatch")
        runtime = self.runtime_fact
        if runtime is not None and (
            runtime.binding != self.binding or runtime.source_manifest_digest != self.source_manifest_digest
        ):
            raise ValueError("workspace_development_runtime_binding_mismatch")
        if self.state == "ready":
            if (runtime is None or runtime.status != "running" or self.health_probe is None
                    or self.health_probe.outcome != "passed" or self.ready_probe is None
                    or self.ready_probe.outcome != "passed" or self.ready_probe.process_id != runtime.process_id
                    or self.health_probe.process_id != runtime.process_id
                    or self.health_probe.runner != runtime.runner or self.ready_probe.runner != runtime.runner
                    or self.ready_probe.observed_migration_revision != self.migration_revision
                    or self.data_generation < 1):
                raise ValueError("workspace_development_ready_requires_verified_facts")
        if self.state in {"suspended", "disposed"}:
            if (self.stop_fact is None or self.stop_fact.outcome != "confirmed_stopped"
                    or self.stop_fact.binding != self.binding
                    or (runtime is not None and runtime.status == "running")):
                raise ValueError("workspace_development_stopped_requires_confirmation")
        if (self.state == "failed") != (self.failure_code is not None):
            raise ValueError("workspace_development_failure_reason_mismatch")
        return self
