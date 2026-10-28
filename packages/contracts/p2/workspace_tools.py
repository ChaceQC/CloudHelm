"""Validated inputs for the developer's bounded workspace code tools."""

from pydantic import Field, field_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p1.workspace_git import workspace_path


class WorkspaceToolRequest(Contract):
    workspace_id: Identifier
    expected_manifest_digest: Digest | None = Field(
        default=None, description="Reuse the previous result's digest when continuing a page."
    )


class WorkspacePathRequest(WorkspaceToolRequest):
    path: str = Field(default="", description="Portable path relative to the workspace; empty means its root.")

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value, allow_root=True)


class WorkspaceListDirectory(WorkspacePathRequest):
    """List direct children of a workspace directory."""

    offset: int = Field(default=0, strict=True, ge=0)
    max_entries: int = Field(default=64, strict=True, ge=1, le=64)


class WorkspaceReadFile(WorkspaceToolRequest):
    """Read bounded, filtered UTF-8 text from one workspace file."""

    path: str
    start_line: int = Field(default=1, strict=True, ge=1)
    start_column: int = Field(default=1, strict=True, ge=1)
    max_lines: int = Field(default=120, strict=True, ge=1, le=160)

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value)


class WorkspaceSearch(WorkspacePathRequest):
    """Search filtered workspace text with a case-sensitive literal string."""

    query: str = Field(strict=True, min_length=1, max_length=256)
    offset: int = Field(default=0, strict=True, ge=0)
    max_results: int = Field(default=32, strict=True, ge=1, le=32)

    @field_validator("query")
    @classmethod
    def check_query(cls, value: str) -> str:
        if any(char in "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029" for char in value):
            raise ValueError("workspace_search_query_multiline")
        return value


class WorkspaceDiff(WorkspaceToolRequest):
    """View a bounded file diff against the materialized base commit."""

    path: str

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return workspace_path(value)


WORKSPACE_TOOL_SCHEMAS = {
    "workspace.list_directory": WorkspaceListDirectory,
    "workspace.read_file": WorkspaceReadFile,
    "workspace.search": WorkspaceSearch,
    "workspace.diff": WorkspaceDiff,
}
