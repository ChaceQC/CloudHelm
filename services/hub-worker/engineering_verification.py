"""Bounded code observations from the exact fixed workspace candidate."""

from types import SimpleNamespace

from modules.agent_runtime.code_reading import _append_page, read_workspace_code
from modules.agent_runtime.source_context import safe_context_text, secret_context_path
from modules.workspaces.safe_paths import WorkspaceFileError, read_regular
from modules.workspaces.workspace_views import diff_result, observe
from packages.contracts.p1.workspace_git import content_digest


def _candidate_diff(git, files, candidate, query):
    if query.path and secret_context_path(query.path):
        raise WorkspaceFileError("workspace_code_secret_path")
    observation = observe(files)
    if observation.digest != candidate.manifest_digest:
        raise WorkspaceFileError("workspace_manifest_mismatch")
    binding = candidate.binding
    source = git.resolve_source(binding.project_id, binding.source_id, binding.source_revision)
    with git.open_commit(source, candidate.parent_commit) as (baseline, read_file):
        old_entries = {entry.path: entry for entry in baseline.files}
        new_entries = {entry.path: entry for entry in observation.manifest.files}
        paths = []
        for path in sorted(old_entries.keys() | new_entries.keys(), key=lambda value: value.encode("utf-8")):
            if secret_context_path(path) or (query.path and path != query.path
                                             and not path.startswith(query.path + "/")):
                continue
            before, after = old_entries.get(path), new_entries.get(path)
            if before is None or after is None or before.model_dump(exclude={"blob_id"}) != after.model_dump():
                paths.append(path)
        result = {"candidate_id": candidate.candidate_id, "candidate_commit": candidate.candidate_commit,
                  "baseline_commit": candidate.parent_commit, "manifest_digest": candidate.manifest_digest,
                  "path": query.path, "offset": query.offset, "total_entries": len(paths), "files": [],
                  "truncated": True, "next_offset": query.offset}
        for path in paths[query.offset:]:
            if len(result["files"]) == query.max_entries:
                break
            before, after = old_entries.get(path), new_entries.get(path)
            old = b"" if before is None else read_file(before) if before.size_bytes <= 65536 else None
            new = b"" if after is None else read_regular(files, path, 65536) if after.size_bytes <= 65536 else None
            if after is not None and new is not None and content_digest(new) != after.content_digest:
                raise WorkspaceFileError("workspace_file_changed")
            diff = diff_result(binding, path, before, after, old, new)
            patch, redacted = diff.patch, False
            if patch:
                old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
                redacted = (safe_context_text(patch) != patch or safe_context_text(old_text) != old_text
                            or safe_context_text(new_text) != new_text)
                if redacted:
                    patch = "[REDACTED]"
            encoded = patch.encode("utf-8")
            item = {
                "path": path, "kind": "added" if before is None else "deleted" if after is None else "modified",
                "before": {"digest": before.content_digest, "mode": before.mode} if before else None,
                "after": {"digest": after.content_digest, "mode": after.mode} if after else None,
                "patch": encoded[:8192].decode("utf-8", errors="ignore"), "binary": diff.binary,
                "truncated": diff.truncated or diff.binary or redacted or len(encoded) > 8192,
                "reason_code": "secret_content" if redacted else "output_limit" if len(encoded) > 8192 else diff.reason_code,
            }
            if _append_page(result, "files", item, query.max_entries):
                continue
            if result["files"]:
                break
            item.update(patch="", truncated=True, reason_code="output_limit")
            _append_page(result, "files", item, query.max_entries)
        else:
            result["next_offset"] = None
        result["truncated"] = result["next_offset"] is not None or any(item["truncated"] for item in result["files"])
        return result


def read_candidate_code(runtime, build_record, name, query):
    names = {
        "candidate.list_directory": "workspace.list_directory",
        "candidate.read_file": "workspace.read_file",
    }
    if name not in names and name != "candidate.diff":
        raise WorkspaceFileError("agent_verification_candidate_tool_unknown")
    candidate = build_record.fixed_inputs.candidate
    if candidate.candidate_id.startswith("integration-candidate-"):
        raise WorkspaceFileError("agent_verification_candidate_source_unsupported")

    with runtime.registry.admit(0) as storage:
        intent = runtime._intent(candidate.freeze_operation_id)
        with runtime._git(storage, candidate.binding.project_id) as git:
            store = runtime._candidate_store(storage, git, intent, reconciliation=True)
            try:
                with store.open_candidate(candidate.freeze_operation_id) as (receipt, files):
                    if receipt.snapshot != candidate:
                        raise WorkspaceFileError("agent_verification_candidate_receipt_mismatch")
                    if name == "candidate.diff":
                        return _candidate_diff(git, files, candidate, query)
                    request = SimpleNamespace(**query.model_dump(), expected_manifest_digest=candidate.manifest_digest)
                    result = read_workspace_code(files, candidate.binding, names[name], request)
                    result.pop("binding")
                    return {**result, "candidate_id": candidate.candidate_id,
                            "candidate_commit": candidate.candidate_commit}
            finally:
                store.close()
