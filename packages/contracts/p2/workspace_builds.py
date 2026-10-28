"""Developer tools for freezing a workspace and building a fixed candidate."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision


class WorkspaceSubmitCandidate(Contract):
    """Freeze the current workspace content as a physical candidate."""

    workspace_id: Identifier
    expected_workspace_revision: Revision
    expected_write_generation: Revision
    expected_manifest_digest: Digest


class BuildRequest(Contract):
    """Request a build for a previously frozen workspace candidate."""

    workspace_id: Identifier
    candidate_id: Identifier


class BuildResult(Contract):
    """Read the current build view and a bounded page of diagnostics."""

    operation_id: Identifier
    log_role: Literal["backend", "frontend"] = "backend"
    log_offset: int = Field(default=0, strict=True, ge=0)
    max_bytes: int = Field(default=8192, strict=True, ge=4, le=8192)


WORKSPACE_BUILD_SCHEMAS = {
    "workspace.submit_candidate": WorkspaceSubmitCandidate,
    "build.request": BuildRequest,
    "build.result": BuildResult,
}

WORKSPACE_BUILD_WRITES = {"workspace.submit_candidate", "build.request"}
