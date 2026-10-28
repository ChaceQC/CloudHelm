"""Bounded developer tools for the existing Workspace environment lifecycle."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p1.development_environment import DataRevision, DevelopmentEnvironmentId


class WorkspacePrepareEnvironment(Contract):
    """Prepare the declared development environment for this workspace."""

    workspace_id: Identifier
    expected_workspace_revision: Revision
    expected_write_generation: Revision


class WorkspaceControlEnvironment(WorkspacePrepareEnvironment):
    """Suspend, resume or dispose the existing development environment."""

    environment_id: DevelopmentEnvironmentId
    action: Literal["suspend", "resume", "dispose"]
    expected_environment_revision: Revision
    expected_data_revision: DataRevision
    expected_data_generation: Revision


class WorkspaceEnvironmentStatus(Contract):
    """Read the most recent development environment for this workspace."""

    workspace_id: Identifier


class WorkspaceEnvironmentLogs(WorkspaceEnvironmentStatus):
    """Read bounded, filtered logs from a declared development service."""

    environment_id: DevelopmentEnvironmentId
    service: Literal["backend", "postgres"]
    max_lines: int = Field(default=80, strict=True, ge=1, le=160)


WORKSPACE_ENVIRONMENT_SCHEMAS = {
    "workspace.prepare_environment": WorkspacePrepareEnvironment,
    "workspace.control_environment": WorkspaceControlEnvironment,
    "workspace.environment_status": WorkspaceEnvironmentStatus,
    "workspace.environment_logs": WorkspaceEnvironmentLogs,
}

WORKSPACE_ENVIRONMENT_WRITES = {
    "workspace.prepare_environment", "workspace.control_environment",
}
