"""Workspace commands describe bounded intent; physical receipts are never inputs."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_git import WorkspaceBinding, WorkspaceFile, workspace_path
from packages.contracts.p1.workspace_records import WorkspaceRecord


class WorkspaceTaskGuard(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    input_set_ref: EngineeringRef

    @field_validator("input_set_ref")
    @classmethod
    def check_input(cls, value):
        expect_kind(value, "input_set")
        return value


class CreateWorkspaceRequest(WorkspaceTaskGuard):
    kind: Literal["create"] = "create"
    goal: str | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("goal")
    @classmethod
    def check_goal(cls, value):
        if value is not None and not value.strip():
            raise ValueError("workspace_goal_required")
        return value


class WorkspaceVersionGuard(WorkspaceTaskGuard):
    expected_workspace_revision: Revision
    expected_write_generation: Revision


class MaterializeWorkspaceRequest(WorkspaceVersionGuard):
    kind: Literal["materialize"] = "materialize"


class MutateWorkspaceFileRequest(WorkspaceVersionGuard):
    """Only content identity is durable; trusted ingress stages the actual bytes."""

    kind: Literal["mutate"] = "mutate"
    action: Literal["write", "delete"]
    path: str
    expected_manifest_digest: Digest
    expected_file: WorkspaceFile | None
    replacement: WorkspaceFile | None

    @field_validator("path")
    @classmethod
    def check_path(cls, value):
        return workspace_path(value)

    @model_validator(mode="after")
    def check_change(self):
        for value in (self.expected_file, self.replacement):
            if value is not None and value.path != self.path:
                raise ValueError("workspace_file_path_mismatch")
        if self.action == "delete":
            if self.expected_file is None or self.replacement is not None:
                raise ValueError("workspace_delete_invalid")
        elif self.replacement is None or self.replacement == self.expected_file:
            raise ValueError("workspace_write_invalid_or_unchanged")
        return self


class SubmitWorkspaceCandidateRequest(WorkspaceVersionGuard):
    kind: Literal["candidate"] = "candidate"
    expected_manifest_digest: Digest


WorkspaceRequest = Annotated[
    CreateWorkspaceRequest | MaterializeWorkspaceRequest | MutateWorkspaceFileRequest
    | SubmitWorkspaceCandidateRequest,
    Field(discriminator="kind"),
]


class WorkspaceCommandResult(Contract):
    command_id: Identifier
    task_id: Identifier
    kind: Literal["create", "materialize", "mutate", "candidate"]
    outcome: Literal["created", "accepted", "rejected"]
    code: Identifier
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    input_set_ref: EngineeringRef
    workspace_id: Identifier | None = None
    binding: WorkspaceBinding | None = None
    operation_id: Identifier | None = None
    request_digest: Digest | None = None

    @model_validator(mode="after")
    def check_result(self):
        expect_kind(self.input_set_ref, "input_set")
        if self.binding is not None and (self.binding.task_id != self.task_id
                                        or self.binding.workspace_id != self.workspace_id):
            raise ValueError("workspace_result_binding_mismatch")
        if (self.outcome == "accepted") != (self.operation_id is not None and self.request_digest is not None):
            raise ValueError("workspace_operation_result_invalid")
        if self.outcome != "accepted" and (self.operation_id is not None or self.request_digest is not None):
            raise ValueError("workspace_operation_result_invalid")
        if self.outcome != "rejected" and self.binding is None:
            raise ValueError("workspace_result_binding_required")
        if self.outcome == "created" and self.kind != "create":
            raise ValueError("workspace_create_result_invalid")
        if self.kind == "create" and self.outcome == "accepted":
            raise ValueError("workspace_create_result_invalid")
        return self


class WorkspaceHttpResult(Contract):
    status_code: Literal[201, 202, 409, 422]
    body: WorkspaceCommandResult


class WorkspaceView(Contract):
    workspace: WorkspaceRecord
    task_version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    work_item_revision: Revision
    work_item_state: Identifier
    pending_operation_ids: tuple[Identifier, ...] = Field(max_length=128)
