"""Build requests bind declared inputs; they contain no command or success claim."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_git import workspace_path

BUILD_REQUEST_SCHEMA = "p1-build-request-r1"
BuildArtifactRole = Literal["frontend", "backend", "postgres"]


class BuildFileInput(Contract):
    """A relative file in the candidate or the controlled recipe bundle."""

    origin: Literal["candidate", "controlled_recipe"] = "candidate"
    path: str
    digest: Digest

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value)


class BuildDefinition(Contract):
    schema_revision: Literal["p1-build-definition-r1"] = "p1-build-definition-r1"
    recipes: tuple[BuildFileInput, ...] = Field(min_length=1, max_length=16)
    locks: tuple[BuildFileInput, ...] = Field(min_length=1, max_length=32)
    toolchain_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=8)
    base_image_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=16)
    platform: Literal["linux/amd64"] = "linux/amd64"
    descriptor: BuildFileInput
    compose: BuildFileInput
    runtime_contract_ref: EngineeringRef
    config_schema: BuildFileInput
    migrations: tuple[BuildFileInput, ...] = Field(min_length=1, max_length=128)
    acceptance_assets_ref: EngineeringRef
    parameter_set_ref: EngineeringRef | None = None
    output_roles: tuple[BuildArtifactRole, ...] = ("frontend", "backend", "postgres")

    @model_validator(mode="after")
    def check_bindings(self):
        for reference in (*self.toolchain_refs, *self.base_image_refs):
            expect_kind(reference, "artifact")
        expect_kind(self.runtime_contract_ref, "runtime")
        expect_kind(self.acceptance_assets_ref, "acceptance_assets")
        if self.parameter_set_ref is not None:
            expect_kind(self.parameter_set_ref, "parameter_set")
        if len(self.output_roles) != 3 or set(self.output_roles) != {"frontend", "backend", "postgres"}:
            raise ValueError("build_output_roles_incomplete")
        files = (*self.recipes, *self.locks, self.descriptor, self.compose, self.config_schema, *self.migrations)
        identities = {}
        for item in files:
            identity = item.origin, item.path.casefold()
            if identity in identities and identities[identity] != item:
                raise ValueError("build_file_identity_conflict")
            identities[identity] = item
        return self


class RequestBuildRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    candidate_id: Identifier
    input_set_ref: EngineeringRef
    definition: BuildDefinition

    @model_validator(mode="after")
    def check_input(self):
        expect_kind(self.input_set_ref, "input_set")
        return self


class BuildCommandResult(Contract):
    command_id: Identifier
    project_id: Identifier
    task_id: Identifier
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    outcome: Literal["accepted", "rejected"]
    code: Identifier
    build_run_id: Identifier | None = None
    operation_id: Identifier | None = None
    request_digest: Digest | None = None
    build_input_digest: Digest | None = None

    @model_validator(mode="after")
    def check_acceptance(self):
        fields = (self.build_run_id, self.operation_id, self.request_digest, self.build_input_digest)
        if (self.outcome == "accepted" and any(value is None for value in fields)
                or self.outcome == "rejected" and any(value is not None for value in fields)):
            raise ValueError("build_acceptance_binding_invalid")
        return self


class BuildHttpResult(Contract):
    status_code: Literal[202, 409, 422]
    body: BuildCommandResult
