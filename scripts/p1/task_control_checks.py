"""Task command ordering/closure checks using actual application methods."""

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.tables import task_completion_reports, tasks
from packages.contracts.p1.task_internal import InvalidateTaskInputRequest
from packages.contracts.p1.task_requests import CreateTaskRequest, StartTaskRequest
from scripts.p1.task_completion_fixture import stage_completion
from scripts.p1.task_operation_fixture import (
    changed_source, close_unstarted, operation_reference, redeliver_closure, register_unknown_write, write_request,
)
from scripts.p1.task_probe import PROJECT, require


def expect_rejection(call, code):
    try:
        reply = call()
    except TaskBoundaryError as error:
        require(error.status_code == 409 and error.code == code, "task_wrong_rejection")
    else:
        require(reply.status_code == 409 and reply.body.code == code, "task_rejection_missing")


def run_submission_checks(probe):
    actor, request, key = probe.actor(), probe.create_request(), probe.key("create-dedupe")
    with UnitOfWork(probe.pools.control) as uow:
        before = uow.connection.scalar(select(func.count()).select_from(tasks).where(tasks.c.project_id == PROJECT))
    created = probe.app.create(actor, PROJECT, request, idempotency_key=key)
    replay = probe.app.create(actor, PROJECT, request, idempotency_key=key)
    require(created == replay and created.status_code == 201, "task_create_replay_changed")
    changed = probe.declaration.model_copy(update={"goal": "A different synthetic request."})
    expect_rejection(lambda: probe.app.create(actor, PROJECT, CreateTaskRequest(
        expected_project_revision=request.expected_project_revision, declaration=changed,
    ), idempotency_key=key), "idempotency_digest_conflict")
    with UnitOfWork(probe.pools.control) as uow:
        after = uow.connection.scalar(select(func.count()).select_from(tasks).where(tasks.c.project_id == PROJECT))
    require(after == before + 1, "task_create_identity_duplicated")
    body = created.body
    wrong = StartTaskRequest(expected_version=body.version + 1, expected_control_revision=body.control_revision,
                             expected_input_validity_revision=body.input_validity_revision)
    wrong_key = probe.key("start-version")
    rejected = probe.app.start(actor, body.task_id, wrong, idempotency_key=wrong_key)
    require(rejected.status_code == 409 and rejected.body.code == "resource_revision_conflict", "task_start_version_not_checked")
    start = StartTaskRequest(expected_version=body.version, expected_control_revision=body.control_revision,
                             expected_input_validity_revision=body.input_validity_revision)
    start_key = probe.key("start-dedupe")
    accepted = probe.app.start(actor, body.task_id, start, idempotency_key=start_key)
    snapshot = probe.snapshot(body.task_id)
    require(probe.app.start(actor, body.task_id, start, idempotency_key=start_key) == accepted, "task_start_replay_changed")
    require(probe.app.start(actor, body.task_id, wrong, idempotency_key=wrong_key) == rejected, "task_rejected_result_not_fixed")
    expect_rejection(lambda: probe.app.start(actor, body.task_id, wrong, idempotency_key=start_key), "idempotency_digest_conflict")
    require(probe.snapshot(body.task_id) == snapshot and snapshot[0]["version"] == body.version + 1
            and snapshot[1]["items"] == 1 and snapshot[1]["bindings"] == 1, "task_start_not_once")
    return {"create_stable_identity_and_digest": True, "start_dedupe_version_and_fixed_rejection": True}


def _immutable_report(probe, report):
    try:
        with probe.pools.control.begin() as connection:
            connection.execute(update(task_completion_reports).where(
                task_completion_reports.c.report_id == report.report_id,
            ).values(report_digest="sha256:" + "0" * 64))
    except DBAPIError as error:
        require(getattr(error.orig, "sqlstate", None) == "42501", "task_report_wrong_database_rejection")
    else:
        require(False, "task_report_database_mutation_allowed")
    require(probe.app.report(probe.actor(), report.task_id) == report, "task_report_changed")


def _completed(probe, state):
    seeded = stage_completion(probe, state=state)
    request, key = probe.complete_request(seeded.task_id), probe.key("complete-" + state)
    result = probe.app.complete(probe.actor(), seeded.task_id, request, idempotency_key=key)
    require(result.status_code == 200 and result.body.outcome == "completed", "task_synthetic_completion_failed")
    report = probe.app.report(probe.actor(), seeded.task_id)
    require(report.basis.human_test.conclusion is None and not report.basis.human_test.is_completion_gate,
            "task_fixture_fabricated_human_acceptance")
    require(probe.app.complete(probe.actor(), seeded.task_id, request, idempotency_key=key) == result,
            "task_completion_replay_changed")
    changed = request.model_copy(update={"expected_input_validity_revision": request.expected_input_validity_revision + 1})
    expect_rejection(lambda: probe.app.complete(probe.actor(), seeded.task_id, changed, idempotency_key=key),
                     "idempotency_digest_conflict")
    fixed = probe.app.complete(probe.actor(), seeded.task_id, request, idempotency_key=probe.key("complete-new-key"))
    require(fixed.status_code == 200 and fixed.body.outcome == "already_completed"
            and fixed.body.completion_report_id == report.report_id, "task_completed_old_version_not_fixed")
    snapshot = probe.snapshot(seeded.task_id)
    require(snapshot[0]["version"] == request.expected_version + 1
            and snapshot[0]["control_revision"] == request.expected_control_revision + 1
            and snapshot[1]["reports"] == 1, "task_completion_not_unique")
    return seeded, request, report


def run_completion_checks(probe):
    active, original_request, report = _completed(probe, "active")
    _completed(probe, "waiting_input")
    _immutable_report(probe, report)
    fresh = probe.create("draft-source")
    expect_rejection(lambda: probe.app.complete(probe.actor(), fresh.task_id, probe.complete_request(fresh.task_id),
                                                idempotency_key=probe.key("draft-complete")), "completion_source_not_allowed")
    for state in ("paused", "failed"):
        seeded = stage_completion(probe, state=state)
        expect_rejection(lambda: probe.app.complete(probe.actor(), seeded.task_id, probe.complete_request(seeded.task_id),
                                                    idempotency_key=probe.key("source-rejected")), "completion_source_not_allowed")
    before = probe.row(active.task_id)
    invalidation = InvalidateTaskInputRequest(
        expected_version=original_request.expected_version,
        expected_control_revision=original_request.expected_control_revision,
        expected_input_validity_revision=original_request.expected_input_validity_revision,
        change_ref=changed_source(probe), reason="synthetic_late_input",
    )
    archived = probe.app.invalidate_input(probe.actor(), active.task_id, invalidation, idempotency_key=probe.key("late-input"))
    require(archived.body.outcome == "impact_archived" and probe.row(active.task_id) == before
            and probe.app.report(probe.actor(), active.task_id) == report, "task_late_input_reopened_completion")
    expect_rejection(lambda: probe.app.start(probe.actor(), active.task_id, StartTaskRequest(
        expected_version=before["version"], expected_control_revision=before["control_revision"],
        expected_input_validity_revision=before["input_validity_revision"],
    ), idempotency_key=probe.key("completed-start")), "task_progress_closed")
    reference = operation_reference(probe, active, label="after-completion")
    expect_rejection(lambda: probe.app.register_write_intent(probe.actor(), active.task_id, write_request(probe, active, reference),
                                                            idempotency_key=probe.key("closed-write")), "task_progress_closed")
    return {"active_and_waiting_input_completion": True, "completion_replay_and_new_key_fixed_report": True,
            "draft_paused_failed_completion_rejected": True, "unique_immutable_report_and_single_revision": True,
            "completed_progress_closed_and_late_input_archived": True, "no_fabricated_human_conclusion": True}


def run_operation_checks(probe):
    seeded = stage_completion(probe)
    reference = register_unknown_write(probe, seeded)
    reply = probe.app.complete(probe.actor(), seeded.task_id, probe.complete_request(seeded.task_id),
                               idempotency_key=probe.key("unknown-write"))
    require(reply.status_code == 409 and reply.body.code == "writes_unsettled"
            and any(block.object_id == reference.object_id for block in reply.body.blockers), "task_unknown_write_not_blocked")
    receipt = close_unstarted(probe, seeded, reference)
    completed = probe.app.complete(probe.actor(), seeded.task_id, probe.complete_request(seeded.task_id),
                                   idempotency_key=probe.key("closed-unstarted"))
    require(completed.status_code == 200 and completed.body.outcome == "completed", "task_closed_unstarted_not_reconciled")
    before = probe.snapshot(seeded.task_id)
    report = probe.app.report(probe.actor(), seeded.task_id)
    redeliver_closure(probe, receipt)
    require(probe.snapshot(seeded.task_id) == before and probe.app.report(probe.actor(), seeded.task_id) == report,
            "task_late_operation_fact_revived_task")
    return {"unknown_write_blocks_completion": True, "synthetic_unstarted_closure_gate": True,
            "late_operation_redelivery_does_not_revive": True}
