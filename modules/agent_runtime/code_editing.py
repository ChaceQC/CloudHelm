"""Prepare bounded text edits under the caller's workspace authorization and root lock."""

from modules.agent_runtime.source_context import safe_context_text, secret_context_path
from modules.workspaces.safe_paths import WorkspaceFileError, exists_at, read_regular
from modules.workspaces.workspace_views import file_parent, observe
from packages.contracts.p1.workspace_git import WorkspaceBinding, WorkspaceFile, content_digest
from packages.contracts.p2.workspace_edits import WorkspaceApplyPatch, WorkspaceCreateFile


def prepare_workspace_edit(
    files: int, binding: WorkspaceBinding, name: str, request: WorkspaceCreateFile | WorkspaceApplyPatch,
) -> tuple[WorkspaceFile | None, WorkspaceFile, bytes]:
    """Return existing metadata, replacement metadata and bytes; never write the workspace."""
    if name not in {"workspace.create_file", "workspace.apply_patch"}:
        raise WorkspaceFileError("workspace_edit_tool_unknown")
    if request.workspace_id != binding.workspace_id:
        raise WorkspaceFileError("workspace_binding_mismatch")
    if request.expected_workspace_revision != binding.workspace_revision:
        raise WorkspaceFileError("workspace_revision_conflict")
    if request.expected_write_generation != binding.write_generation:
        raise WorkspaceFileError("workspace_write_generation_conflict")
    if secret_context_path(request.path):
        raise WorkspaceFileError("workspace_code_secret_path")
    if request.path.split("/")[-1].casefold() in {".gitmodules", ".lfsconfig"}:
        raise WorkspaceFileError("git_extension_unsupported")
    observed = observe(files)
    if request.expected_manifest_digest != observed.digest:
        raise WorkspaceFileError("workspace_manifest_mismatch")
    entry = next((item for item in observed.manifest.files if item.path == request.path), None)
    if name == "workspace.create_file":
        with file_parent(files, request.path) as (parent, leaf):
            try:
                exists = entry is not None or exists_at(parent, leaf)
            except OSError:
                raise WorkspaceFileError("workspace_file_unavailable") from None
        if exists:
            raise WorkspaceFileError("workspace_file_already_exists")
        text = request.content_utf8
        mode = request.mode
    else:
        if entry is None:
            raise WorkspaceFileError("workspace_code_file_not_found")
        if request.expected_file_digest != entry.content_digest:
            raise WorkspaceFileError("workspace_file_digest_mismatch")
        if entry.size_bytes > 65536:
            raise WorkspaceFileError("workspace_code_file_too_large")
        with file_parent(files, request.path) as (parent, leaf):
            original = read_regular(parent, leaf, 65536)
        if content_digest(original) != entry.content_digest:
            raise WorkspaceFileError("workspace_file_changed")
        try:
            old = original.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceFileError("workspace_code_not_text") from None
        if "\x00" in old:
            raise WorkspaceFileError("workspace_code_not_text")
        if safe_context_text(old) != old:
            raise WorkspaceFileError("workspace_edit_secret_content")
        start = old.find(request.old_text)
        if start < 0:
            raise WorkspaceFileError("workspace_patch_no_match")
        if old.find(request.old_text, start + 1) >= 0:
            raise WorkspaceFileError("workspace_patch_ambiguous")
        text = old[:start] + request.new_text + old[start + len(request.old_text):]
        mode = entry.mode
    if safe_context_text(text) != text:
        raise WorkspaceFileError("workspace_edit_secret_content")
    data = text.encode("utf-8")
    if len(data) > 65536:
        raise WorkspaceFileError("workspace_edit_text_too_large")
    replacement = WorkspaceFile(path=request.path, mode=mode, size_bytes=len(data), content_digest=content_digest(data))
    if replacement == entry:
        raise WorkspaceFileError("workspace_edit_unchanged")
    return entry, replacement, data
