"""Authenticated executor messages; no credentials, host paths, shell or log bodies."""

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p0.permit_contracts import StepPermit, TimeMapping
from packages.contracts.p1.delivery_records import (
    DeploymentApproval, DeploymentPlan, EnvironmentBinding, EnvironmentState, ReleaseManifest, TargetObservation,
)


class RemoteHello(Contract):
    executor_instance: Identifier
    generation: Revision
    mapping_epoch: Identifier
    clock_continuity_id: Identifier
    sample_nonce: str = Field(pattern=r"^[0-9a-f]{32}$")


class RemoteTimeSample(Contract):
    hello: RemoteHello
    hub_incarnation: Identifier
    time_domain: Literal["hub-monotonic-us-v1"] = "hub-monotonic-us-v1"
    time_epoch: Identifier
    channel_binding_id: Identifier
    hub_sample_us: int = Field(strict=True, ge=0)
    support_evidence_digest: Digest


class RemotePlan(Contract):
    operation_id: Identifier
    plan_digest: Digest
    plan: DeploymentPlan
    manifest: ReleaseManifest
    approval: DeploymentApproval

    @model_validator(mode="after")
    def identities(self):
        from modules.delivery.release_recipe import delivery_digest

        if (self.plan_digest != delivery_digest(self.plan)
                or self.plan.manifest_digest != delivery_digest(self.manifest)
                or self.plan.release_id != self.manifest.release_id
                or self.plan_digest != self.approval.plan_digest
                or self.operation_id != self.approval.operation_id
                or self.plan.plan_id != self.approval.plan_id):
            raise ValueError("remote_plan_binding_invalid")
        return self


class RemoteStepResult(Contract):
    operation_id: Identifier
    plan_digest: Digest
    step_id: Identifier
    input_digest: Digest
    grant_id: Identifier
    executor_instance: Identifier
    generation: Revision
    status: Literal["succeeded", "failed_known", "unknown"]
    state: EnvironmentState
    evidence_digest: Digest
    observed_at: UtcTimestamp
    database_operation_id: Identifier | None = None
    database_input_digest: Digest | None = None
    database_postchecks: tuple[Literal["schema_integrity", "data_integrity", "application_probe"], ...] = ()
    health_started_at: UtcTimestamp | None = None
    health_finished_at: UtcTimestamp | None = None
    health_samples: int = Field(default=0, strict=True, ge=0, le=1000)


class RemotePermitRequest(Contract):
    operation_id: Identifier
    plan_digest: Digest
    step_id: Identifier
    mapping: TimeMapping
    actual_state_digest: Digest
    predecessor_results_digest: Digest
    closed_unstarted_grants: tuple[Identifier, ...] = Field(default=(), max_length=64)


class RemotePermit(Contract):
    grant: StepPermit
    environment_revision: Revision


class RemoteObservationRequest(Contract):
    observation: TargetObservation


class RemotePoll(Contract):
    executor_instance: Identifier
    generation: Revision


class RemotePollResult(Contract):
    deployment: RemotePlan | None = None
    status: Literal["idle", "ready", "waiting_authorization"]
    code: Identifier


class RemoteBindings(Contract):
    bindings: tuple[EnvironmentBinding, ...] = Field(default=(), max_length=16)
