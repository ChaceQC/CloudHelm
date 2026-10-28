"""Fixed, bounded checks for the current development workspace."""

from typing import Literal

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p1.development_environment import DevelopmentEnvironmentId


class WorkspaceCheck(Contract):
    """Run one supported check against the specified workspace and environment."""

    workspace_id: Identifier
    environment_id: DevelopmentEnvironmentId
    expected_workspace_revision: Revision
    expected_write_generation: Revision
    expected_manifest_digest: Digest
    check: Literal["backend.syntax", "backend.http"]


WORKSPACE_CHECK_SCHEMAS = {"workspace.check": WorkspaceCheck}
