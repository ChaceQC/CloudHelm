"""Bounded integration steps with a current admission fence for Git publication."""

import time
from contextlib import contextmanager

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import require_ordinary_progress
from modules.identity.actors import actor_for_command
from modules.integration.git_merge import MergeGitStore
from modules.integration.merge_queue import check_entry_task, record_event
from modules.integration.merge_records import entry_for_attempt, queue_head, read_attempt, read_entry, read_review, save_entry
from modules.integration.merge_validity import verified_final
from modules.workspaces.candidate_view import retain_candidate_manifest
from modules.workspaces.git_objects import read_commit_files
from packages.contracts.p1.workspace_git import CandidateSnapshot, content_digest
from packages.contracts.p2.merge_queue import IntegrationAttempt


_CLOSE_APPLY_ON = {"merge_inputs_not_current", "input_not_current", "verification_not_applicable", "task_progress_closed"}


def _access(uow, attempt_id, phase, *, starting=False, command_id=None):
    entry = entry_for_attempt(uow.connection, attempt_id)
    command_id = command_id or (entry.apply_command_id if phase == "apply" else entry.command_id)
    actor = actor_for_command(uow, command_id)
    task, _ = lock_task_access(uow, actor, entry.task_id, "candidate.submit")
    entry = read_entry(uow.connection, entry.entry_id)
    if entry.attempt_id != attempt_id:
        raise TaskBoundaryError("integration_attempt_not_current")
    if starting:
        head = queue_head(uow.connection, entry.project_id)
        expected_state = "applying" if phase == "apply" else "preparing"
        if head is None or head.entry_id != entry.entry_id or entry.state != expected_state:
            raise TaskBoundaryError("merge_entry_not_head")
        check_entry_task(uow.connection, task, entry)
        if phase == "apply":
            _, view = verified_final(uow.connection, task, entry, entry.verification_report_id)
            review = read_review(uow.connection, entry.review_id)
            if (review is None or review.conclusion != "approved" or review.attempt_id != attempt_id
                    or review.input_set_ref != view.report.evidence.input_set_ref):
                raise TaskBoundaryError("integration_review_required")
        require_ordinary_progress(uow.connection, task["task_id"], expected_version=task["version"],
            expected_control_revision=entry.control_revision,
            expected_input_validity_revision=entry.input_validity_revision)
    return entry


def execute_merge(runtime, operation_id):
    """Execute or reconcile one stage by its original Git attempt."""
    reconciling = operation_id.startswith("merge-reconcile-")
    reconcile_command_id = None
    if reconciling:
        reconcile_command_id, _, attempt_id = operation_id.removeprefix("merge-reconcile-").partition("-")
        phase = None
    else:
        phase = "prepare" if operation_id.startswith("merge-prepare-") else "apply"
        prefix = "merge-" + phase + "-"
        if not operation_id.startswith(prefix):
            raise TaskBoundaryError("merge_operation_invalid")
        attempt_id = operation_id[len(prefix):]
    application = runtime.merges
    with UnitOfWork(application.control_engine) as uow:
        entry = _access(uow, attempt_id, phase, command_id=reconcile_command_id)
    if entry.state in {"merged", "withdrawn"}:
        return {"entry_id": entry.entry_id, "state": entry.state}
    if reconciling:
        phase = "apply" if entry.state == "applying" else "prepare"
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
                    with UnitOfWork(application.control_engine) as uow:
                        _access(uow, attempt_id, phase, starting=True)
                    fixed = store.prepare(source, attempt_id, entry.candidate.candidate_commit)
                if fixed.state == "pending":
                    return {"entry_id": entry.entry_id, "state": "unknown"}
                snapshot = None
                if fixed.state == "prepared":
                    with git.integration_repository(source) as directory:
                        _, files = read_commit_files(directory, fixed.integrated_commit, "", time.monotonic() + 60)
                        manifest_digest = retain_candidate_manifest(directory, files)
                    suffix = content_digest(attempt_id.encode("utf-8"))[7:]
                    snapshot = CandidateSnapshot(binding=entry.candidate.binding,
                        candidate_id="integration-candidate-" + suffix, candidate_commit=fixed.integrated_commit,
                        parent_commit=fixed.base_commit, freeze_operation_id=attempt_id,
                        storage_id="candidate-" + suffix, manifest_digest=manifest_digest)
                attempt = IntegrationAttempt(attempt_id=attempt_id, entry_id=entry.entry_id,
                    project_id=entry.project_id, task_id=entry.task_id, base_commit=fixed.base_commit,
                    candidate_commit=fixed.candidate_commit, state=fixed.state, snapshot=snapshot,
                    conflict_paths=fixed.conflict_paths, conflict_paths_truncated=fixed.conflict_paths_truncated,
                    reason_code=fixed.reason_code)
                return _finish_prepare(application, entry, attempt, reconcile_command_id or entry.command_id)
            return _execute_apply(application, entry, fixed, store, source, storage, reconcile_command_id)


def _execute_apply(application, entry, fixed, store, source, storage, reconcile_command_id):
    if fixed is None or fixed.state != "prepared":
        raise TaskBoundaryError("integration_final_candidate_required")
    command_id = reconcile_command_id or entry.apply_command_id

    @contextmanager
    def start_gate():
        with UnitOfWork(application.control_engine) as uow:
            _access(uow, entry.attempt_id, "apply", starting=True, command_id=command_id)
            # Keep evidence invalidation ordered with the bounded Git ref writes.
            yield

    outcome = {"applied": "merged", "closed": "closed", "unknown": "unknown"}.get(fixed.apply_state)
    if outcome is None:
        try:
            if reconcile_command_id is not None:
                with start_gate():
                    outcome = "unknown"
            else:
                storage.observe()
                outcome = store.apply(source, entry.attempt_id, fixed.base_commit, fixed.integrated_commit,
                                      start_gate=start_gate)
        except TaskBoundaryError as error:
            if error.code not in _CLOSE_APPLY_ON:
                raise
            outcome = store.close_apply(source, entry.attempt_id)
    return _finish_apply(application, entry, outcome, store, source, command_id)


def _finish_prepare(application, original, attempt, command_id):
    with UnitOfWork(application.engine) as uow:
        actor = actor_for_command(uow, command_id)
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


def _finish_apply(application, original, outcome, store, source, command_id):
    if outcome == "unknown":
        return {"entry_id": original.entry_id, "state": "unknown"}
    tip = store.current_tip(source) if outcome == "baseline_changed" else None
    with UnitOfWork(application.engine) as uow:
        actor = actor_for_command(uow, command_id)
        lock_task_access(uow, actor, original.task_id, "candidate.submit")
        entry = read_entry(uow.connection, original.entry_id, for_update=True)
        if entry.attempt_id != original.attempt_id:
            raise TaskBoundaryError("integration_attempt_not_current")
        if entry.state in {"merged", "withdrawn"}:
            return {"entry_id": entry.entry_id, "state": entry.state}
        if outcome in {"merged", "closed"}:
            state = "merged" if outcome == "merged" else "withdrawn"
            entry = save_entry(uow.connection, entry, state=state)
            record_event(uow, entry, "merge-completed-" + original.attempt_id, "integration." + state,
                         entry, command_id)
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
