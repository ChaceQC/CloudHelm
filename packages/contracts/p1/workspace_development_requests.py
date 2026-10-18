"""Public Workspace development requests contain intent, never Runner claims."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind
from packages.contracts.p1.development_environment import (
    DataRevision, DevelopmentEnvironmentId, DevelopmentOperationId,
    WorkspaceDevelopmentEnvironmentObservation, WorkspaceDevelopmentState,
)
from packages.contracts.p1.workspace_git import WorkspaceBinding


class WorkspaceDevelopmentTaskGuard(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    input_set_ref: EngineeringRef

    @field_validator("input_set_ref")
    @classmethod
    def check_input_set(cls, value):
        expect_kind(value, "input_set")
        return value


class PrepareWorkspaceDevelopmentRequest(WorkspaceDevelopmentTaskGuard):
    action: Literal["prepare"] = "prepare"
    expected_workspace_revision: Revision
    expected_write_generation: Revision


class _WorkspaceDevelopmentControlRequest(WorkspaceDevelopmentTaskGuard):
    expected_workspace_revision: Revision
    expected_write_generation: Revision
    expected_environment_revision: Revision
    expected_data_revision: DataRevision
    expected_data_generation: Revision


class SuspendWorkspaceDevelopmentRequest(_WorkspaceDevelopmentControlRequest):
    action: Literal["suspend"] = "suspend"


class ResumeWorkspaceDevelopmentRequest(_WorkspaceDevelopmentControlRequest):
    action: Literal["resume"] = "resume"


class ResetWorkspaceDevelopmentDataRequest(_WorkspaceDevelopmentControlRequest):
    action: Literal["reset_data"] = "reset_data"
    target_data_revision: DataRevision


class DisposeWorkspaceDevelopmentRequest(_WorkspaceDevelopmentControlRequest):
    action: Literal["dispose"] = "dispose"


WorkspaceDevelopmentControlRequest = Annotated[
    SuspendWorkspaceDevelopmentRequest
    | ResumeWorkspaceDevelopmentRequest
    | ResetWorkspaceDevelopmentDataRequest
    | DisposeWorkspaceDevelopmentRequest,
    Field(discriminator="action"),
]
WorkspaceDevelopmentRequest = Annotated[
    PrepareWorkspaceDevelopmentRequest
    | SuspendWorkspaceDevelopmentRequest
    | ResumeWorkspaceDevelopmentRequest
    | ResetWorkspaceDevelopmentDataRequest
    | DisposeWorkspaceDevelopmentRequest,
    Field(discriminator="action"),
]


class WorkspaceDevelopmentCommandResult(Contract):
    command_id: Identifier
    task_id: Identifier
    workspace_id: Identifier
    action: Literal["prepare", "suspend", "resume", "reset_data", "dispose"]
    outcome: Literal["accepted", "rejected"]
    code: Identifier
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    environment_id: DevelopmentEnvironmentId | None = None
    operation_id: DevelopmentOperationId | None = None
    request_digest: Digest | None = None
    environment_revision: Revision | None = None

    @model_validator(mode="after")
    def check_acceptance(self):
        fields = (self.operation_id, self.request_digest, self.environment_revision)
        if self.outcome == "accepted":
            if self.environment_id is None or any(value is None for value in fields):
                raise ValueError("workspace_development_acceptance_invalid")
        elif any(value is not None for value in fields):
            raise ValueError("workspace_development_rejection_has_operation")
        return self


class WorkspaceDevelopmentHttpResult(Contract):
    status_code: Literal[202, 404, 409, 422]
    body: WorkspaceDevelopmentCommandResult


class WorkspaceDevelopmentEnvironmentView(Contract):
    environment_id: Identifier
    workspace_id: Identifier
    binding: WorkspaceBinding
    environment_revision: Revision
    state: WorkspaceDevelopmentState
    pending_operation_ids: tuple[Identifier, ...] = Field(max_length=128)
    latest_observation: WorkspaceDevelopmentEnvironmentObservation | None = None


class WorkspaceDevelopmentOperationView(Contract):
    result: WorkspaceDevelopmentCommandResult
    accepted_environment_revision: Revision
    operation_state: Literal["pending", "unknown", "succeeded", "failed"]
    accepted_at: UtcTimestamp
    closed_at: UtcTimestamp | None = None
    observation: WorkspaceDevelopmentEnvironmentObservation | None = None
