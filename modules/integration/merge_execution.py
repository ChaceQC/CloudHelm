"""Bounded integration steps; Git I/O stays outside short application transactions."""

import time

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import require_ordinary_progress
from modules.identity.actors import actor_for_command
from modules.integration.git_merge import MergeGitStore
from modules.integration.merge_queue import check_entry_task, record_event
from modules.integration.merge_records import entry_for_attempt, queue_head, read_attempt, read_entry, save_entry
from modules.integration.merge_validity import verified_final
from modules.workspaces.git_objects import read_commit_files
from packages.contracts.p1.workspace_git import CandidateSnapshot, content_digest, manifest_bytes
from packages.contracts.p2.merge_queue import IntegrationAttempt


def _access(application, attempt_id, phase, *, starting=False):
    with UnitOfWork(application.control_engine) as uow:
        entry = entry_for_attempt(uow.connection, attempt_id)
        command_id = entry.apply_command_id if phase == "apply" else entry.command_id
        actor = actor_for_command(uow, command_id)
        task, _ = lock_task_access(uow, actor, entry.task_id, "candidate.submit")
        if starting:
            require_ordinary_progress(uow.connection, task["task_id"], expected_version=task["version"],
                expected_control_revision=entry.control_revision,
                expected_input_validity_revision=entry.input_validity_revision)
            check_entry_task(uow.connection, task, entry)
            head = queue_head(uow.connection, entry.project_id)
            expected_state = "applying" if phase == "apply" else "preparing"
            if head is None or head.entry_id != entry.entry_id or entry.state != expected_state:
                raise TaskBoundaryError("merge_entry_not_head")
            if phase == "apply":
                from modules.integration.merge_records import read_review

                _, view = verified_final(uow.connection, task, entry, entry.verification_report_id)
                review = read_review(uow.connection, entry.review_id)
                if (review is None or review.conclusion != "approved" or review.attempt_id != attempt_id
                        or review.input_set_ref != view.report.evidence.input_set_ref):
                    raise TaskBoundaryError("integration_review_required")
        return entry


def execute_merge(runtime, operation_id):
    """One physical stage per invocation; replay queries its original Git operation."""
    reconciling = operation_id.startswith("merge-reconcile-")
    if reconciling:
        attempt_id = operation_id[len("merge-reconcile-") + 33:]
        with UnitOfWork(runtime.control_engine) as uow:
            entry = entry_for_attempt(uow.connection, attempt_id)
        phase = "apply" if entry.state == "applying" else "prepare"
    else:
        phase = "prepare" if operation_id.startswith("merge-prepare-") else "apply"
    prefix = "merge-" + phase + "-"
    if not reconciling and not operation_id.startswith(prefix):
        raise TaskBoundaryError("merge_operation_invalid")
    if not reconciling:
        attempt_id = operation_id[len(prefix):]
    application = runtime.merges
    entry = _access(application, attempt_id, phase)
    if entry.state in {"merged", "withdrawn"}:
        return {"entry_id": entry.entry_id, "state": entry.state}
    with runtime.registry.admit(128 * 1024**2) as storage:
        with runtime._git(storage, entry.project_id) as git:
            source = git.resolve_source(entry.project_id, entry.source.source_id, entry.source.source_revision)
            if source != entry.source:
                raise TaskBoundaryError("merge_source_changed")
            store = MergeGitStore(git)
            fixed = store.query(source, attempt_id)
            if phase == "prepare":
                if fixed is None:
                    if reconciling:
                        return {"entry_id": entry.entry_id, "state": "unknown"}
                    _access(application, attempt_id, phase, starting=True)
                    fixed = store.prepare(source, attempt_id, entry.candidate.candidate_commit)
                if fixed.state == "pending":
                    return {"entry_id": entry.entry_id, "state": "unknown"}
                snapshot = None
                if fixed.state == "prepared":
                    with git.integration_repository(source) as directory:
                        _, files = read_commit_files(directory, fixed.integrated_commit, "", time.monotonic() + 60)
                    suffix = content_digest(attempt_id.encode("utf-8"))[7:]
                    snapshot = CandidateSnapshot(binding=entry.candidate.binding,
                        candidate_id="integration-candidate-" + suffix, candidate_commit=fixed.integrated_commit,
                        parent_commit=fixed.base_commit, freeze_operation_id=attempt_id,
                        storage_id="candidate-" + suffix, manifest_digest=content_digest(manifest_bytes(files)))
                attempt = IntegrationAttempt(attempt_id=attempt_id, entry_id=entry.entry_id,
                    project_id=entry.project_id, task_id=entry.task_id, base_commit=fixed.base_commit,
                    candidate_commit=fixed.candidate_commit, state=fixed.state, snapshot=snapshot,
                    conflict_paths=fixed.conflict_paths, conflict_paths_truncated=fixed.conflict_paths_truncated,
                    reason_code=fixed.reason_code)
                return _finish_prepare(application, entry, attempt)
            if fixed is None or fixed.state != "prepared":
                raise TaskBoundaryError("integration_final_candidate_required")
            if fixed.apply_state == "unknown":
                return {"entry_id": entry.entry_id, "state": "unknown"}
            outcome = "merged" if fixed.applied else None
            if outcome is None:
                if reconciling:
                    from modules.collaboration.guards import read_task

                    with UnitOfWork(application.control_engine) as uow:
                        task = read_task(uow.connection, entry.task_id)
                    if task["cancel_requested_at"] is not None and fixed.apply_state == "not_started":
                        return _finish_apply(application, entry, "withdrawn", store, source)
                    return {"entry_id": entry.entry_id, "state": "unknown"}
                _access(application, attempt_id, phase, starting=True)
                storage.observe()
                outcome = store.apply(source, attempt_id, fixed.base_commit, fixed.integrated_commit)
            return _finish_apply(application, entry, outcome, store, source)


def _finish_prepare(application, original, attempt):
    with UnitOfWork(application.engine) as uow:
        actor = actor_for_command(uow, original.command_id)
        lock_task_access(uow, actor, original.task_id, "candidate.submit")
        entry = read_entry(uow.connection, original.entry_id, for_update=True)
        if entry.attempt_id != attempt.attempt_id:
            raise TaskBoundaryError("integration_attempt_not_current")
        if read_attempt(uow.connection, attempt.attempt_id) is None:
            record_event(uow, entry, attempt.attempt_id, "integration.prepared", attempt, original.command_id)
        if entry.state == "preparing":
            entry = save_entry(uow.connection, entry,
                state="awaiting_evidence" if attempt.state == "prepared" else "conflict")
        return {"entry_id": entry.entry_id, "state": entry.state}


def _finish_apply(application, original, outcome, store, source):
    if outcome == "unknown":
        return {"entry_id": original.entry_id, "state": "unknown"}
    tip = store.current_tip(source) if outcome == "baseline_changed" else None
    with UnitOfWork(application.engine) as uow:
        actor = actor_for_command(uow, original.apply_command_id)
        lock_task_access(uow, actor, original.task_id, "candidate.submit")
        entry = read_entry(uow.connection, original.entry_id, for_update=True)
        if entry.attempt_id != original.attempt_id:
            raise TaskBoundaryError("integration_attempt_not_current")
        if entry.state == "merged":
            return {"entry_id": entry.entry_id, "state": entry.state}
        if outcome in {"merged", "withdrawn"}:
            entry = save_entry(uow.connection, entry, state=outcome)
            record_event(uow, entry, "merge-completed-" + original.attempt_id, "integration." + outcome,
                         entry, original.apply_command_id)
        else:
            suffix = content_digest((original.attempt_id + ":" + tip).encode("utf-8"))[7:]
            entry = save_entry(uow.connection, entry, state="queued", attempt_id="merge-attempt-" + suffix,
                command_id=original.apply_command_id, review_id=None,
                verification_report_id=None, apply_command_id=None)
            record_event(uow, entry, "merge-requeued-" + suffix, "integration.baseline_changed",
                         entry, original.apply_command_id)
        application.start_head(uow, entry.project_id)
        entry = read_entry(uow.connection, entry.entry_id)
        return {"entry_id": entry.entry_id, "state": entry.state, "attempt_id": entry.attempt_id}
