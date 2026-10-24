"""Public identity projections; authentication proofs are never request fields."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.identity_contracts import Action


IDENTITY_SCHEMA_REVISION = "p1-identity-r1"
MemberRole = Literal["developer", "reviewer", "deployment_approver"]
IdentityErrorCode = Literal[
    "authentication_required", "authentication_failed", "identity_not_current",
    "permission_denied", "role_action_denied", "delegation_not_current",
    "authorization_binding_mismatch", "policy_not_current", "recorded_actor_not_found",
]


class IdentityErrorResponse(Contract):
    code: IdentityErrorCode


class CurrentIdentity(Contract):
    schema_revision: Literal["p1-identity-r1"] = IDENTITY_SCHEMA_REVISION
    user_id: Identifier
    display_name: str = Field(min_length=1, max_length=160)
    session_id: Identifier
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone_required")
        return value


class ProjectView(Contract):
    schema_revision: Literal["p1-identity-r1"] = IDENTITY_SCHEMA_REVISION
    project_id: Identifier
    name: str = Field(min_length=1, max_length=160)
    owner_user_id: Identifier
    revision: Revision
    permission_revision: Revision
    policy_revision: Revision


class ProjectPage(Contract):
    items: tuple[ProjectView, ...] = Field(max_length=100)
    next_cursor: Identifier | None = None


class RoleBindingView(Contract):
    binding_id: Identifier
    project_id: Identifier
    user_id: Identifier
    role: MemberRole
    actions: tuple[Action, ...] = Field(min_length=1, max_length=20)
    revision: Revision
    revoked: bool

    @model_validator(mode="after")
    def distinct_actions(self) -> "RoleBindingView":
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("duplicate_actions")
        return self


class RoleBindingPage(Contract):
    items: tuple[RoleBindingView, ...] = Field(max_length=100)
    next_cursor: Identifier | None = None
