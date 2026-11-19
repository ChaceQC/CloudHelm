"""Bounded diffs of current workspace files and already fixed human-return snapshots."""

from modules.agent_runtime.source_context import safe_context_text, secret_context_path
from modules.workspaces.candidate_freeze import CandidateFreezeController
from modules.workspaces.candidate_store import CandidateStore
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.safe_paths import WorkspaceFileError, read_regular
from modules.workspaces.workspace_views import diff_result, file_parent, file_state


def read_workspace_diff(runtime, spec, query):
    if secret_context_path(query.path):
        raise WorkspaceFileError("workspace_code_secret_path")
    with runtime.registry.admit(0) as storage, runtime._git(storage, spec.binding.project_id) as git:
        service = WorkspaceFileService(storage.workspace_root, git, lambda _: spec)
        try:
            diff = service.diff(spec.materialization_operation_id, query.path,
                                expected_manifest_digest=query.expected_manifest_digest)
            result = diff.model_dump(mode="json")
            patch = safe_context_text(diff.patch).encode("utf-8")
            result.update(patch=patch[:8192].decode("utf-8", errors="ignore"),
                          truncated=diff.truncated or len(patch) > 8192)
            if len(patch) > 8192:
                result["reason_code"] = "output_limit"
            return result
        finally:
            service.close()


def read_handoff_context(runtime, handoff, source):
    record = runtime.handoffs.read_returned_record(handoff, source)
    baseline, returned = record.baseline, record.returned
    specs = {baseline.operation_id: record.takeover_spec, returned.operation_id: record.return_spec}
    changes = tuple(change for change in record.changes if not secret_context_path(change.path))
    patches, total = [], 0
    with runtime.registry.admit(0) as storage, runtime._git_for_source(storage, source) as git:
        # This reader has no registered writer scopes and can only resolve the two recorded operations.
        store = CandidateStore(storage.workspace_root, git, specs.__getitem__, CandidateFreezeController({}.__getitem__))
        try:
            for change in changes[:8]:
                contents, entries = [], []
                for receipt in (baseline, returned):
                    with store.open_candidate(receipt.operation_id) as (actual, files):
                        if actual != receipt:
                            raise WorkspaceFileError("agent_context_handoff_snapshot_mismatch")
                        entry, _ = file_state(files, change.path)
                        entries.append(entry)
                        if entry is None:
                            contents.append(b"")
                        elif entry.size_bytes > 65536:
                            contents.append(None)
                        else:
                            with file_parent(files, change.path) as (parent, name):
                                contents.append(read_regular(parent, name, 65536))
                if entries != [change.before, change.after]:
                    raise WorkspaceFileError("agent_context_handoff_change_mismatch")
                diff = diff_result(returned.snapshot.binding, change.path,
                                   entries[0], entries[1], contents[0], contents[1])
                patch = safe_context_text(diff.patch)
                encoded = patch.encode("utf-8")
                remaining = max(0, 8192 - total)
                patches.append({"path": change.path, "before": change.before.model_dump(mode="json") if change.before else None,
                                "after": change.after.model_dump(mode="json") if change.after else None,
                                "patch": encoded[:remaining].decode("utf-8", errors="ignore"),
                                "binary": diff.binary, "truncated": diff.truncated or len(encoded) > remaining})
                total += min(len(encoded), remaining)
        finally:
            store.close()
    return {"handoff_id": record.handoff_id, "baseline": baseline.snapshot.model_dump(mode="json"),
            "returned": returned.snapshot.model_dump(mode="json"), "change_count": len(record.changes),
            "reason": record.reason, "changes": [change.model_dump(mode="json") for change in changes[:32]],
            "changes_truncated": len(changes) > 32,
            "diff_ref": "/api/workspaces/" + record.workspace_id + "/handoffs/" + record.handoff_id, "patches": patches,
            "patches_truncated": len(changes) > 8, "filtered_change_count": len(record.changes) - len(changes)}
