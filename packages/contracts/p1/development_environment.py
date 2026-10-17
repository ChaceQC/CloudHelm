"""Fixed local artifact-verification inputs and observations, without business approval."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind
from packages.contracts.p1.build_artifacts import ArtifactContent
from packages.contracts.p1.development_storage import DevelopmentStorageRef

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
