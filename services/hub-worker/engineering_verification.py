"""Bounded code observations from a fixed candidate's Git objects."""

import json

import rfc8785

from modules.agent_runtime.code_reading import _FILE_LIMIT, _PAGE_LIMIT, _TEXT_LIMIT, _append_page, _text_range
from modules.agent_runtime.source_context import safe_context_text, secret_context_path
from modules.integration.candidate_read import CandidateReadSpec
from modules.workspaces.candidate_view import open_candidate_view
from modules.workspaces.safe_paths import WorkspaceFileError
from modules.workspaces.workspace_views import diff_result
from packages.contracts.p1.workspace_git import content_digest
from packages.contracts.p1.workspace_records import workspace_metadata_digest


def _page_cursor(spec: CandidateReadSpec, name: str, query, offset: int) -> str:
    return content_digest(rfc8785.dumps({
        "snapshot_digest": workspace_metadata_digest(spec.snapshot),
        "build_input_set_id": spec.build_input_set_id, "build_input_set_digest": spec.build_input_set_digest,
        "tool": name, "path": query.path, "max_entries": query.max_entries, "offset": str(offset),
    }))


def _validate_page_cursor(spec: CandidateReadSpec, name: str, query) -> None:
    if (query.offset and (query.cursor is None or query.cursor != _page_cursor(spec, name, query, query.offset))
            or not query.offset and query.cursor is not None):
        raise WorkspaceFileError("candidate_read_cursor_mismatch")


def _finish_page(spec: CandidateReadSpec, name: str, query, result: dict) -> dict:
    offset = result["next_offset"]
    result["next_cursor"] = _page_cursor(spec, name, query, offset) if offset is not None else None
    return result


def _candidate_list_directory(view, spec: CandidateReadSpec, name: str, query, base: dict) -> dict:
    prefix = query.path + "/" if query.path else ""
    exists = not query.path
    children = {}
    for path, entry in view.files.items():
        if not path.startswith(prefix):
            continue
        exists = True
        segment, separator, _ = path[len(prefix):].partition("/")
        child = prefix + segment
        if child in children or secret_context_path(child):
            continue
        if separator:
            children[child] = {"path": child, "kind": "directory"}
        else:
            children[child] = {"path": child, "kind": "file", "digest": entry.content_digest,
                               "size_bytes": entry.size_bytes}
    if not exists:
        raise WorkspaceFileError("workspace_directory_unavailable")

    result = {**base, "path": query.path, "offset": query.offset, "total_entries": len(children),
              "entries": [], "truncated": True, "next_offset": query.offset}
    for path in sorted(children, key=lambda value: value.encode("utf-8"))[query.offset:]:
        if not _append_page(result, "entries", children[path], query.max_entries):
            break
    else:
        result.update(truncated=False, next_offset=None)
    return _finish_page(spec, name, query, result)


def _candidate_read_file(view, query, base: dict) -> dict:
    entry = view.files.get(query.path)
    if entry is None:
        raise WorkspaceFileError("workspace_code_file_not_found")
    result = {**base, "path": entry.path, "digest": entry.content_digest, "size_bytes": entry.size_bytes}
    if entry.size_bytes > _FILE_LIMIT:
        reason = "input_limit"
    else:
        data = view.read_file(entry.path, _FILE_LIMIT)
        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError:
            source = None
        if source is None or "\x00" in source:
            reason = "binary"
        elif safe_context_text(source) != source:
            reason = "secret_content"
        else:
            return {**result, **_text_range(source, query, limit_utf8_bytes=True), "reason_code": None}
    return {**result, "start_line": query.start_line, "start_column": query.start_column,
            "end_line": None, "total_lines": None, "content": "", "truncated": True,
            "next_start_line": None, "next_start_column": None, "reason_code": reason}


def _expand_diff(view, binding, item: dict, remaining: int) -> int:
    path = item["path"]
    after = view.files.get(path)
    old = b"" if item["before"] is None else view.read_baseline(path, _FILE_LIMIT)
    if item["before"] is not None and old is not None:
        item["before"]["digest"] = content_digest(old)
    new = b"" if after is None else view.read_file(path, _FILE_LIMIT) if after.size_bytes <= _FILE_LIMIT else None

    # Reuse the unified patch renderer; the Git view supplies the entry metadata.
    diff = diff_result(binding, path, None, None, old, new)
    patch, reason = diff.patch, diff.reason_code
    if patch and (safe_context_text(patch) != patch
                  or any(safe_context_text(source) != source for source in (old.decode("utf-8"), new.decode("utf-8")))):
        patch, reason = "[REDACTED]", "secret_content"
    raw = patch.encode("utf-8")
    if len(raw) > _TEXT_LIMIT:
        patch, reason = raw[:_TEXT_LIMIT].decode("utf-8", errors="ignore"), "output_limit"
    size = len(json.dumps(patch, ensure_ascii=True)) - 2
    if size > remaining:
        patch, reason, size = "", reason or "output_limit", 0
    item.update(patch=patch, binary=diff.binary, truncated=reason is not None, reason_code=reason)
    return remaining - size


def _candidate_diff(view, spec: CandidateReadSpec, name: str, query, base: dict) -> dict:
    prefix = query.path + "/"
    paths = []
    for path in view.baseline.keys() | view.files.keys():
        if secret_context_path(path) or (query.path and path != query.path and not path.startswith(prefix)):
            continue
        before, after = view.baseline.get(path), view.files.get(path)
        if before is None or after is None or (before.mode, before.blob_id) != (after.mode, after.blob_id):
            paths.append(path)
    paths.sort(key=lambda path: path.encode("utf-8"))

    result = {**base, "path": query.path, "offset": query.offset, "total_entries": len(paths), "files": [],
              "truncated": False, "next_offset": None}
    encode = json.JSONEncoder(ensure_ascii=True, separators=(",", ":")).encode
    remaining = _PAGE_LIMIT - len(encode(result))
    # Reserve space for an optional baseline digest and the longest omission reason.
    entry_reserve = len(encode({"digest": spec.snapshot.manifest_digest, "reason_code": "secret_content"}))
    for path in paths[query.offset:query.offset + query.max_entries]:
        before, after = view.baseline.get(path), view.files.get(path)
        item = {
            "path": path, "kind": "added" if before is None else "deleted" if after is None else "modified",
            "before": {"blob_id": before.blob_id, "mode": before.mode} if before else None,
            "after": {"blob_id": after.blob_id, "mode": after.mode, "digest": after.content_digest} if after else None,
            "patch": "", "binary": False, "truncated": False, "reason_code": None,
        }
        size = len(encode(item)) + entry_reserve + 1
        if size > remaining:
            break
        result["files"].append(item)
        remaining -= size
    offset = query.offset + len(result["files"])
    if offset < len(paths):
        result["next_offset"] = offset
    for item in result["files"]:
        remaining = _expand_diff(view, spec.snapshot.binding, item, remaining)
    result["truncated"] = result["next_offset"] is not None or any(item["truncated"] for item in result["files"])
    return _finish_page(spec, name, query, result)


def read_candidate_code(runtime, spec: CandidateReadSpec, name: str, query) -> dict:
    if name not in {"candidate.list_directory", "candidate.read_file", "candidate.diff"}:
        raise WorkspaceFileError("agent_verification_candidate_tool_unknown")
    if query.path and secret_context_path(query.path):
        raise WorkspaceFileError("workspace_code_secret_path")
    if name != "candidate.read_file":
        _validate_page_cursor(spec, name, query)
    snapshot = spec.snapshot
    base = {"candidate_id": snapshot.candidate_id, "candidate_commit": snapshot.candidate_commit,
            "baseline_commit": snapshot.parent_commit, "manifest_digest": snapshot.manifest_digest}
    with (runtime.registry.admit(0) as storage, runtime._git_for_source(storage, spec.git_source) as git,
          open_candidate_view(git, spec.git_source, snapshot, include_baseline=name == "candidate.diff") as view):
        if name == "candidate.list_directory":
            return _candidate_list_directory(view, spec, name, query, base)
        if name == "candidate.read_file":
            return _candidate_read_file(view, query, base)
        return _candidate_diff(view, spec, name, query, base)
