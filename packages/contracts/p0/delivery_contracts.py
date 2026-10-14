"""Separate immutable release inputs from deployment environment bindings."""

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import (
    Contract, Digest, Identifier, ProtocolRevision, Revision,
)
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind


class ServiceArtifact(Contract):
    service_key: Identifier
    platform: Literal["linux/amd64"]
    artifact_ref: EngineeringRef

    @model_validator(mode="after")
    def check_artifact(self):
        expect_kind(self.artifact_ref, "artifact")
        return self


class ReleaseManifest(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    release_id: Identifier
    source_ref: EngineeringRef
    build_input_ref: EngineeringRef
    build_run_ref: EngineeringRef
    services: tuple[ServiceArtifact, ...] = Field(min_length=1, max_length=16)
    runtime_contract_ref: EngineeringRef
    configuration_schema_ref: EngineeringRef
    migration_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=32)
    verification_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=32)
    acceptance_assets_ref: EngineeringRef
    descriptor_ref: EngineeringRef
    compose_ref: EngineeringRef
    parser_revision: Identifier
    variant_ref: EngineeringRef

    @model_validator(mode="after")
    def check_refs(self):
        for ref, kind in (
            (self.source_ref, "source"), (self.build_input_ref, "input_set"),
            (self.build_run_ref, "build"), (self.runtime_contract_ref, "runtime"),
            (self.configuration_schema_ref, "config_schema"),
            (self.acceptance_assets_ref, "acceptance_assets"),
            (self.descriptor_ref, "descriptor"), (self.compose_ref, "compose"),
            (self.variant_ref, "variant"),
        ):
            expect_kind(ref, kind)
        for ref in self.migration_refs:
            expect_kind(ref, "migration")
        for ref in self.verification_refs:
            expect_kind(ref, "evidence")
        if len({service.service_key for service in self.services}) != len(self.services):
            raise ValueError("DUPLICATE_SERVICE_KEY")
        return self


class EnvironmentConfigRevision(Contract):
    environment_id: Identifier
    revision: Revision
    parameter_set_ref: EngineeringRef
    resource_binding_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=16)
    secret_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.parameter_set_ref, "parameter_set")
        for ref in self.resource_binding_refs:
            expect_kind(ref, "resource_binding")
        for ref in self.secret_refs:
            expect_kind(ref, "secret_version")
        return self


class DeploymentPlanBinding(Contract):
    plan_id: Identifier
    plan_digest: Digest
    operation_id: Identifier
    release_ref: EngineeringRef
    environment_config_ref: EngineeringRef
    expected_environment_revision: Revision
    expected_observed_state_digest: Digest
    normalized_spec_ref: EngineeringRef
    input_set_ref: EngineeringRef
    parser_revision: Identifier
    target_installation_id: Identifier
    executor_instance: Identifier
    generation: Revision
    approval_ref: EngineeringRef

    @model_validator(mode="after")
    def check_refs(self):
        for ref, kind in (
            (self.release_ref, "release"), (self.environment_config_ref, "environment_config"),
            (self.normalized_spec_ref, "deployment_spec"), (self.input_set_ref, "input_set"),
            (self.approval_ref, "approval"),
        ):
            expect_kind(ref, kind)
        return self


class P0DeliveryContracts(Contract):
    release_manifest: ReleaseManifest
    environment_config: EnvironmentConfigRevision
    deployment_plan_binding: DeploymentPlanBinding
