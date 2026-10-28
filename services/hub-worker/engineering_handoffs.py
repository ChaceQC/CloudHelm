"""Capture and reconcile workspace handoffs through the existing candidate store."""

import os

from modules.workspaces.candidate_freeze import CandidateFreezeController
from modules.workspaces.candidate_store import CandidateStore
from modules.workspaces.candidate_writers import process_start_ticks
from modules.workspaces.safe_paths import WorkspaceFileError
from modules.workspaces.workspace_views import observe
from packages.contracts.p1.workspace_candidates import WorkspaceWriterScope
from packages.contracts.p1.workspace_git import WorkspaceChange


def execute_handoff(runtime, operation_id):
    """Keep storage admission while reconciling or capturing this one registered operation."""
    with runtime.registry.admit(128 * 1024**2) as storage:
        spec = runtime.handoffs.resolve(operation_id, reconciliation=True)
        record = runtime.handoffs.record_for_operation(operation_id)
        with runtime._git(storage, spec.binding.project_id) as git:
            reconciliation = True

            def resolve(value):
                if value == operation_id:
                    return runtime.handoffs.resolve(value, reconciliation=reconciliation)
                if reconciliation and record.baseline is not None and value == record.baseline.operation_id:
                    return record.takeover_spec
                raise LookupError(value)

            def resolve_scope(scope_id):
                # CandidateStore invokes the freeze controller under the workspace root lock.
                runtime.registry.current_storage()
                current = runtime.handoffs.resolve(operation_id)
                if scope_id != current.runtime_scope_id or scope_id != runtime.runtime_scope_for(current.binding):
                    raise WorkspaceFileError("workspace_runtime_scope_mismatch")
                readers = runtime._development.registered_readers(current.binding)
                pid = os.getpid()
                return WorkspaceWriterScope(scope_id=scope_id, binding=current.binding,
                    service_instance_id=runtime.instance_id, service_pid=pid,
                    service_start_ticks=process_start_ticks(pid), readers=readers)

            store = CandidateStore(storage.workspace_root, git, resolve, CandidateFreezeController(resolve_scope))
            try:
                status = store.query(operation_id)
                if status.state == "not_found":
                    reconciliation = False
                    try:
                        store.capture(operation_id)
                    except WorkspaceFileError:
                        reconciliation = True
                        status = store.query(operation_id)
                        if status.state == "not_found":
                            raise
                    else:
                        reconciliation = True
                        status = store.query(operation_id)
                if status.state != "captured":
                    return {"operation_id": operation_id, "state": "unknown",
                            "code": status.reason_code or "workspace_handoff_unsettled"}

                changes = ()
                if record.return_spec is not None and record.return_spec.candidate_id == spec.candidate_id:
                    if record.baseline is None:
                        raise WorkspaceFileError("workspace_handoff_baseline_unavailable")
                    with store.open_candidate(record.baseline.operation_id) as (baseline, files):
                        if baseline != record.baseline:
                            raise WorkspaceFileError("workspace_handoff_baseline_mismatch")
                        old = {item.path: item for item in observe(files).manifest.files}
                    with store.open_candidate(operation_id) as (returned, files):
                        if returned != status.receipt:
                            raise WorkspaceFileError("workspace_handoff_return_mismatch")
                        new = {item.path: item for item in observe(files).manifest.files}
                    changes = tuple(
                        WorkspaceChange(path=path, kind="added" if path not in old else
                            "deleted" if path not in new else "modified", before=old.get(path), after=new.get(path))
                        for path in sorted(old.keys() | new.keys(), key=lambda value: value.encode("utf-8"))
                        if old.get(path) != new.get(path)
                    )
                result = runtime.handoffs.finish(operation_id, store, changes=changes)
                return {"operation_id": operation_id, "state": "registered", "code": "workspace_handoff_registered",
                        "handoff_id": result.handoff_id, "ownership": result.state,
                        "change_count": len(result.changes)}
            finally:
                store.close()
