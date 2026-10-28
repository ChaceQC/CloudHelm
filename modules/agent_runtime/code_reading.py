"""Bounded observations of source in the current, locked workspace."""

import json
import os
import stat
from contextlib import nullcontext

from modules.agent_runtime.source_context import safe_context_text, secret_context_path
from modules.workspaces.safe_paths import WorkspaceFileError, directory_at, read_regular
from modules.workspaces.workspace_views import file_parent, observe
from packages.contracts.p1.workspace_git import WorkspaceBinding, content_digest


_FILE_LIMIT = 64 * 1024
_TEXT_LIMIT = 8192
_PAGE_LIMIT = 32 * 1024 - 256
_SNIPPET_LIMIT = 240


def _safe_text(files: int, entry) -> str:
    if entry.size_bytes > _FILE_LIMIT:
        raise WorkspaceFileError("workspace_code_file_too_large")
    with file_parent(files, entry.path) as (parent, name):
        data = read_regular(parent, name, _FILE_LIMIT)
    if content_digest(data) != entry.content_digest:
        raise WorkspaceFileError("workspace_file_changed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkspaceFileError("workspace_code_not_text") from None
    if "\x00" in text:
        raise WorkspaceFileError("workspace_code_not_text")
    return safe_context_text(text)


def _append_page(result: dict, field: str, item: dict, limit: int) -> bool:
    items = result[field]
    if len(items) == limit:
        return False
    items.append(item)
    result["next_offset"] = result["offset"] + len(items)
    size = len(json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
    if size > _PAGE_LIMIT:
        items.pop()
        result["next_offset"] = result["offset"] + len(items)
        return False
    return True


def _list_directory(files: int, request, observed, base: dict) -> dict:
    entries = {entry.path: entry for entry in observed.manifest.files}
    directory = directory_at(files, request.path) if request.path else nullcontext(files)
    children = []
    try:
        with directory as parent:
            for name in sorted(os.listdir(parent), key=lambda item: item.encode("utf-8")):
                path = f"{request.path}/{name}" if request.path else name
                if secret_context_path(path):
                    continue
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    children.append({"path": path, "kind": "directory"})
                else:
                    entry = entries.get(path)
                    if entry is None or not stat.S_ISREG(info.st_mode):
                        raise WorkspaceFileError("workspace_file_changed")
                    children.append({"path": path, "kind": "file", "digest": entry.content_digest,
                                     "size_bytes": entry.size_bytes})
    except OSError:
        raise WorkspaceFileError("workspace_directory_unavailable") from None
    result = {**base, "path": request.path, "offset": request.offset, "total_entries": len(children),
              "entries": [], "truncated": True, "next_offset": request.offset}
    for item in children[request.offset:]:
        if not _append_page(result, "entries", item, request.max_entries):
            break
    else:
        result.update(truncated=False, next_offset=None)
    return result


def _read_file(files: int, request, observed, base: dict) -> dict:
    entry = next((entry for entry in observed.manifest.files if entry.path == request.path), None)
    if entry is None:
        raise WorkspaceFileError("workspace_code_file_not_found")
    lines = _safe_text(files, entry).splitlines(keepends=True)
    if request.start_line > max(1, len(lines)):
        raise WorkspaceFileError("workspace_code_line_out_of_range")
    index, column = request.start_line - 1, request.start_column - 1
    if (not lines and column) or (lines and column >= len(lines[index])):
        raise WorkspaceFileError("workspace_code_column_out_of_range")
    pieces, touched, remaining = [], 0, _TEXT_LIMIT
    while index < len(lines) and touched < request.max_lines and remaining:
        part = lines[index][column:]
        take = min(len(part), remaining)
        pieces.append(part[:take])
        touched += 1
        remaining -= take
        if take < len(part):
            column += take
            break
        index += 1
        column = 0
    truncated = index < len(lines)
    return {**base, "path": entry.path, "digest": entry.content_digest, "size_bytes": entry.size_bytes,
            "start_line": request.start_line, "start_column": request.start_column,
            "end_line": index + 1 if column else index, "total_lines": len(lines),
            "content": "".join(pieces), "truncated": truncated,
            "next_start_line": index + 1 if truncated else None,
            "next_start_column": column + 1 if truncated else None}


def _search(files: int, request, observed, base: dict) -> dict:
    entries = observed.manifest.files
    if request.path and not any(entry.path == request.path for entry in entries):
        with directory_at(files, request.path):
            pass
    result = {**base, "path": request.path, "offset": request.offset, "matches": [],
              "skipped_too_large": 0, "skipped_not_text": 0, "skipped_counts_complete": False,
              "truncated": True, "next_offset": request.offset}
    seen = 0
    for entry in entries:
        if secret_context_path(entry.path) or (request.path and entry.path != request.path
                                              and not entry.path.startswith(request.path + "/")):
            continue
        try:
            text = _safe_text(files, entry)
        except WorkspaceFileError as error:
            if error.code == "workspace_code_file_too_large":
                result["skipped_too_large"] += 1
                continue
            if error.code == "workspace_code_not_text":
                result["skipped_not_text"] += 1
                continue
            raise
        for line_number, line in enumerate(text.splitlines(), 1):
            column = line.find(request.query)
            if column < 0:
                continue
            if seen < request.offset:
                seen += 1
                continue
            start = max(0, column - 40)
            item = {"path": entry.path, "digest": entry.content_digest, "line": line_number,
                    "column": column + 1, "snippet_start_column": start + 1,
                    "snippet": line[start:start + _SNIPPET_LIMIT]}
            if not _append_page(result, "matches", item, request.max_results):
                return result
            seen += 1
    result.update(truncated=False, next_offset=None, skipped_counts_complete=True)
    return result


def read_workspace_code(files: int, binding: WorkspaceBinding, name: str, request) -> dict:
    """Read only under the caller's current workspace authorization and root lock."""
    if request.path and secret_context_path(request.path):
        raise WorkspaceFileError("workspace_code_secret_path")
    observed = observe(files)
    manifest_digest = observed.digest
    if request.expected_manifest_digest is not None and request.expected_manifest_digest != manifest_digest:
        raise WorkspaceFileError("workspace_manifest_mismatch")
    base = {"binding": binding.model_dump(mode="json"), "manifest_digest": manifest_digest}
    if name == "workspace.list_directory":
        return _list_directory(files, request, observed, base)
    if name == "workspace.read_file":
        return _read_file(files, request, observed, base)
    if name == "workspace.search":
        return _search(files, request, observed, base)
    raise WorkspaceFileError("workspace_code_tool_unknown")
