"""Fixed project-management and maintenance inputs; no caller assertions."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p1.identity_contracts import MemberRole

GrantableAction = Literal[
    "resource.read", "task.command", "task.cancel", "operation.query",
    "operation.stop", "operation.reconcile", "fact.archive",
]


class RenameProjectRequest(Contract):
    expected_project_revision: Revision
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_name_required")
        return value


class GrantProjectRoleRequest(Contract):
    expected_project_revision: Revision
    expected_permission_revision: Revision
    user_id: Identifier
    role: MemberRole
    actions: tuple[GrantableAction, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct_actions(self) -> "GrantProjectRoleRequest":
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("duplicate_actions")
        return self


class RevokeProjectRoleRequest(Contract):
    expected_project_revision: Revision
    expected_permission_revision: Revision
    binding_id: Identifier


class CreateUserRequest(Contract):
    user_id: Identifier
    display_name: str = Field(min_length=1, max_length=160)


class CreateProjectRequest(Contract):
    project_id: Identifier
    owner_user_id: Identifier
    name: str = Field(min_length=1, max_length=160)


class IssueSessionRequest(Contract):
    user_id: Identifier
    credential_file: str = Field(min_length=1, max_length=4096)
    lifetime_seconds: int = Field(default=28800, strict=True, ge=60, le=86400)


class DisableUserRequest(Contract):
    user_id: Identifier


class RevokeSessionRequest(Contract):
    session_id: Identifier


MaintenanceAction = Literal[
    "maintenance.user.create", "maintenance.project.create", "maintenance.session.issue",
    "maintenance.user.disable", "maintenance.session.revoke",
]


class MaintenanceResource(Contract):
    resource_kind: Literal["user", "project", "device_session"]
    resource_id: Identifier
    user_id: Identifier
    project_id: Identifier | None = None
