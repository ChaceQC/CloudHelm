"""Validated inputs for bounded developer workspace edits."""

from typing import Literal

from pydantic import Field, field_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p1.workspace_git import workspace_path


def _bounded_utf8(value: str) -> str:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("workspace_edit_invalid_utf8") from None
    if size > 65536:
        raise ValueError("workspace_edit_text_too_large")
    if "\x00" in value:
        raise ValueError("workspace_code_not_text")
    return value


class WorkspaceEditRequest(Contract):
    workspace_id: Identifier
    path: str = Field(strict=True, description="Portable path relative to the workspace.")
    expected_workspace_revision: Revision
    expected_write_generation: Revision
    expected_manifest_digest: Digest

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        try:
            return workspace_path(value)
        except UnicodeEncodeError:
            raise ValueError("workspace_path_invalid") from None


class WorkspaceCreateFile(WorkspaceEditRequest):
    """Create one UTF-8 file in an existing workspace directory."""

    content_utf8: str = Field(
        strict=True, max_length=65536, repr=False, description="UTF-8 content, at most 65536 bytes."
    )
    mode: Literal["100644", "100755"] = "100644"

    @field_validator("content_utf8")
    @classmethod
    def check_content(cls, value: str) -> str:
        return _bounded_utf8(value)


class WorkspaceApplyPatch(WorkspaceEditRequest):
    """Replace one uniquely occurring literal text span in an existing file."""

    expected_file_digest: Digest
    old_text: str = Field(
        strict=True, min_length=1, max_length=65536, repr=False,
        description="Nonempty literal text occurring exactly once; at most 65536 UTF-8 bytes.",
    )
    new_text: str = Field(
        strict=True, max_length=65536, repr=False, description="Replacement text, at most 65536 UTF-8 bytes."
    )

    @field_validator("old_text", "new_text")
    @classmethod
    def check_text(cls, value: str) -> str:
        return _bounded_utf8(value)


WORKSPACE_EDIT_SCHEMAS = {
    "workspace.create_file": WorkspaceCreateFile,
    "workspace.apply_patch": WorkspaceApplyPatch,
}
