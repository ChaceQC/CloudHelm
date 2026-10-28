"""Immutable archive delivery inputs; target facts are never public write bodies."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, UtcTimestamp
from packages.contracts.p0.permit_contracts import PlanStep
from packages.contracts.p0.resource_contracts import ResourceVector
from packages.contracts.p1.build_records import BuildArtifactRecord
from packages.contracts.p1.build_requests import BuildDefinition
from packages.contracts.p1.closeout_contracts import DeploymentCloseout
from packages.contracts.p1.compose_contracts import ComposeDeploymentPlan, ComposeEnvironmentConfig, ComposeReleaseSpec

ARCHIVE_VARIANT = "reference-notes-archive-linux-amd64-r1"
SecretVersionReference = Annotated[str, Field(pattern=r"^secret://[A-Za-z0-9._/-]+@v[0-9]+$")]


class ReleaseManifest(Contract):
    schema_revision: Literal["p1-release-manifest-r1"] = "p1-release-manifest-r1"
    release_id: Identifier
    project_id: Identifier
    task_id: Identifier
    build_run_id: Identifier
    build_operation_id: Identifier
    build_input_digest: Digest
    source_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    input_set: InputSet
    definition: BuildDefinition
    variant: Literal["reference-notes-archive-linux-amd64-r1"] = ARCHIVE_VARIANT
    variant_digest: Digest
    artifacts: tuple[BuildArtifactRecord, ...] = Field(min_length=3, max_length=3)
    runtime: ComposeReleaseSpec
    build_observation_id: Identifier
    build_method_ref: EngineeringRef
    verification_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=32)
    verification_configuration: ComposeEnvironmentConfig

    @model_validator(mode="after")
    def complete_artifacts(self):
        if {item.role for item in self.artifacts} != {"backend", "frontend", "postgres"}:
            raise ValueError("release_artifact_roles_incomplete")
        return self


class EnvironmentBinding(Contract):
    binding_id: Identifier
    project_id: Identifier
    environment_id: Identifier
    target_id: Identifier
    installation_id: Identifier
    namespace: str = Field(pattern=r"^ch-[0-9a-f]{32}$")


class TargetRegistration(Contract):
    target_id: Identifier
    installation_id: Identifier
    executor_instance: Identifier
    generation: Revision = Field(ge=1)
    platform: Literal["linux/amd64"] = "linux/amd64"
    docker_identity_kind: Literal["oci_config", "oci_manifest"]
    supported_steps: tuple[str, ...] = Field(min_length=1, max_length=16)
    capacity: ResourceVector


class ObservedService(Contract):
    manifest_digest: Digest
    config_digest: Digest
    loaded_image_id: Digest
    docker_identity_kind: Literal["oci_config", "oci_manifest"]
    state: Literal["running", "stopped"]


class EnvironmentState(Contract):
    environment_revision: Revision
    release_id: Identifier | None = None
    config_revision_id: Identifier | None = None
    services: dict[str, ObservedService] = Field(default_factory=dict, max_length=16)
    database_revision: Identifier | None = None
    unregistered_resources: tuple[Identifier, ...] = Field(default=(), max_length=64)


class TargetObservation(Contract):
    observation_id: Identifier
    binding_id: Identifier
    target_id: Identifier
    installation_id: Identifier
    executor_instance: Identifier
    generation: Revision = Field(ge=1)
    reconciled: StrictBool
    state: EnvironmentState
    available_secret_refs: tuple[SecretVersionReference, ...] = Field(default=(), max_length=64)
    observed_at: UtcTimestamp


class EnvironmentConfigRevision(Contract):
    schema_revision: Literal["p1-environment-config-r1"] = "p1-environment-config-r1"
    binding_id: Identifier
    revision: Revision = Field(ge=1)
    configuration: ComposeEnvironmentConfig
    parameter_contract_digest: Digest
    resources: ResourceVector


class DeploymentPlan(Contract):
    schema_revision: Literal["p1-deployment-plan-r1"] = "p1-deployment-plan-r1"
    plan_id: Identifier
    project_id: Identifier
    release_id: Identifier
    manifest_digest: Digest
    variant_digest: Digest
    binding: EnvironmentBinding
    executor_instance: Identifier
    generation: Revision
    platform: Literal["linux/amd64"] = "linux/amd64"
    docker_identity_kind: Literal["oci_config", "oci_manifest"]
    expected_state: EnvironmentState
    expected_state_digest: Digest
    configuration: EnvironmentConfigRevision
    normalized_spec: ComposeDeploymentPlan
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=16)
    step_inputs: dict[str, dict] = Field(min_length=1, max_length=16)
    start_before: UtcTimestamp
    max_runtime_seconds: int = Field(strict=True, ge=60, le=1860)
    health_window_seconds: Literal[30] = 30
    policy_revision: Revision
    authorization_revision: Revision
    required_approval_action: Literal["deployment.approve"] = "deployment.approve"
    new_steps_require_online_permit: Literal[True] = True
    on_disconnect: Literal["wait_and_reconcile"] = "wait_and_reconcile"
    compensation: Literal["stop_and_reconcile"] = "stop_and_reconcile"

    @model_validator(mode="after")
    def fixed_step_inputs(self):
        import hashlib
        import rfc8785

        digest = lambda value: "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()
        if (len({step.step_id for step in self.steps}) != len(self.steps)
                or set(self.step_inputs) != {step.step_id for step in self.steps}
                or self.configuration.binding_id != self.binding.binding_id
                or self.normalized_spec.config_revision_id != self.configuration.configuration.config_revision_id):
            raise ValueError("deployment_plan_input_binding_invalid")
        for step in self.steps:
            value = self.step_inputs[step.step_id]
            if (step.input_ref != step.step_id or step.input_digest != digest(value)
                    or step.preconditions_digest != digest(value.get("preconditions"))
                    or step.postconditions_digest != digest(value.get("postconditions"))):
                raise ValueError("deployment_step_digest_invalid")
        return self


class DeploymentApproval(Contract):
    approval_id: Identifier
    plan_id: Identifier
    plan_digest: Digest
    binding_id: Identifier
    config_revision_id: Identifier
    approver_user_id: Identifier
    authorization_revision: Revision
    policy_revision: Revision
    approved_at: UtcTimestamp
    expires_at: UtcTimestamp
    operation_id: Identifier


class DeliveryObject(Contract):
    object_id: Identifier
    digest: Digest
    value: (
        ReleaseManifest | EnvironmentBinding | EnvironmentConfigRevision | DeploymentPlan | DeploymentApproval | DeploymentCloseout
    )


class EnvironmentView(Contract):
    object_id: Identifier
    digest: Digest
    value: EnvironmentBinding
    environment_revision: Revision
    config_revision: Revision
    active_operation_id: Identifier | None
    observation: TargetObservation | None
    observation_state_digest: Digest | None
    observation_status: Literal["missing", "current", "stale", "unknown"]


class DeploymentPreflight(Contract):
    plan_id: Identifier
    operation_id: Identifier
    plan_digest: Digest
    checked_at: UtcTimestamp
    status: Literal["ready_for_remote_handoff"] = "ready_for_remote_handoff"
    grants_start_permission: Literal[False] = False


class DeploymentView(Contract):
    plan: DeliveryObject
    approval: DeploymentApproval | None
    operation_id: Identifier | None
    status: Literal[
        "approval_pending", "awaiting_remote_agent", "execution_registered", "needs_reconciliation",
        "failed_known", "succeeded", "closeout_pending", "closed_retained",
    ]
    environment_revision: Revision


class DeploymentStagedEvent(Contract):
    operation_id: Identifier
    plan_id: Identifier
    status: Literal["awaiting_remote_agent"] = "awaiting_remote_agent"
    blocking_code: Identifier
    physical_execution_started: Literal[False] = False


class DeploymentRegisteredEvent(Contract):
    plan_id: Identifier
    plan_digest: Digest
    environment_revision: Revision
