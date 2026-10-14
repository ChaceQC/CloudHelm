"""Safe command receipts shared by Project application handlers and the CLI."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p1.identity_contracts import ProjectView, RoleBindingView


ManagementRejectionCode = Literal[
    "resource_revision_conflict", "permission_revision_conflict", "target_user_not_current",
    "role_binding_not_found", "role_action_denied", "revision_limit_reached",
]


class ProjectCommandResult(Contract):
    command_id: Identifier
    project_id: Identifier
    outcome: Literal["renamed", "role_granted", "role_revoked", "unchanged", "rejected"]
    code: Identifier
    project: ProjectView
    role_binding: RoleBindingView | None = None


class ProjectHttpResult(Contract):
    status_code: Literal[200, 409]
    body: ProjectCommandResult


class ProjectChangedEvent(Contract):
    project: ProjectView
    change: Literal["renamed", "role_granted", "role_revoked"]
    role_binding: RoleBindingView | None = None


class MaintenanceResult(Contract):
    operation_id: Identifier
    outcome: Literal["created", "issued", "disabled", "revoked", "unchanged"]
    user_id: Identifier
    project_id: Identifier | None = None
    session_id: Identifier | None = None
    credential_file: str | None = Field(default=None, max_length=4096)
    expires_at: datetime | None = None
