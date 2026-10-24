"""Bounded delivery commands contain references and parameters, never success claims."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp
from packages.contracts.p0.resource_contracts import ResourceVector
from packages.contracts.p1.compose_contracts import ComposeEnvironmentConfig


class CreateReleaseRequest(Contract):
    build_operation_id: Identifier
    variant_digest: Digest
    verification_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=32)
    verification_configuration: ComposeEnvironmentConfig


class CreateEnvironmentRequest(Contract):
    environment_id: Identifier
    target_id: Identifier
    installation_id: Identifier


class CreateEnvironmentConfigRequest(Contract):
    release_id: Identifier
    expected_config_revision: Revision
    configuration: ComposeEnvironmentConfig
    resources: ResourceVector


class CreateDeploymentPlanRequest(Contract):
    release_id: Identifier
    config_revision_id: Identifier
    expected_environment_revision: Revision
    expected_state_digest: Digest
    start_before: UtcTimestamp


class ApproveDeploymentPlanRequest(Contract):
    plan_digest: Digest
    expires_at: UtcTimestamp


class CheckDeploymentPlanRequest(Contract):
    plan_digest: Digest


class DeliveryCommandResult(Contract):
    command_id: Identifier
    project_id: Identifier
    outcome: Literal["created", "approved", "rejected"]
    code: Identifier
    object_id: Identifier | None = None
    digest: Digest | None = None
    operation_id: Identifier | None = None


class DeliveryHttpResult(Contract):
    status_code: Literal[200, 201, 409, 422]
    body: DeliveryCommandResult


class DeliveryCommandBody(Contract):
    target_id: Identifier | None
    request: dict
