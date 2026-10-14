"""Actual Task workflow consumption and business replay after real worker effects."""

from sqlalchemy import func, select

from database.commands import commands
from database.uow import UnitOfWork
from modules.collaboration.tables import work_items
from packages.contracts.p1.identity_requests import RevokeSessionRequest
from packages.contracts.p1.task_internal import InvalidateTaskInputRequest
from packages.contracts.p1.task_requests import ReconcileTaskRequest, StartTaskRequest
from scripts.p1.runtime_processes import worker_running
from scripts.p1.task_control_checks import expect_rejection
from scripts.p1.task_completion_fixture import stage_completion
from scripts.p1.task_operation_fixture import changed_source, close_unstarted, register_unknown_write
from scripts.p1.task_probe import require


def _step_records(probe, workflow_id):
    with UnitOfWork(probe.pools.control) as uow:
        return uow.connection.scalar(select(func.count()).select_from(commands).where(
            commands.c.resource_kind == "workflow_binding", commands.c.resource_id == workflow_id,
        ))


def _unknown_cancellation(probe):
    seeded = stage_completion(probe)
    reference = register_unknown_write(probe, seeded)
    accepted = probe.app.cancel(probe.actor(), seeded.task_id, probe.cancel_request(seeded.task_id),
                                idempotency_key=probe.key("unknown-cancel"))
    probe.wait_workflow(accepted.body.workflow_id)
    row = probe.row(seeded.task_id)
    require(row["state"] != "cancelled" and row["cancel_requested_at"] is not None
            and row["ordinary_progress_closed"] and row["completion_report_id"] is None,
            "task_unknown_physical_operation_cancelled")
    close_unstarted(probe, seeded, reference)
    reconciled = probe.app.reconcile(probe.actor(), seeded.task_id, ReconcileTaskRequest(
        expected_version=row["version"], expected_control_revision=row["control_revision"], purpose="cancellation",
    ), idempotency_key=probe.key("physical-reconciled"))
    require(reconciled.status_code == 202, "task_reconciliation_not_accepted")
    probe.wait_workflow(reconciled.body.workflow_id)
    require(probe.row(seeded.task_id)["state"] == "cancelled", "task_reconciled_cancellation_not_finished")


def run_runtime_checks(probe):
    draft = probe.create("cancel-without-delivery")
    draft_cancel = probe.app.cancel(probe.actor(), draft.task_id, probe.cancel_request(draft.task_id),
                                    idempotency_key=probe.key("cancel-draft"))
    require(draft_cancel.status_code == 202, "task_zero_operation_cancel_not_accepted")
    started = probe.start(probe.create("real-worker"))
    old_session = probe.session.session_id
    probe.maintenance.revoke_session(RevokeSessionRequest(session_id=old_session))
    probe.issue_session("owner-next")
    with worker_running(probe.fixture):
        probe.wait_workflow(started.workflow_id)
        probe.wait_workflow(draft_cancel.body.workflow_id)
        current = probe.row(started.task_id)
        with UnitOfWork(probe.pools.control) as uow:
            item = uow.connection.execute(select(work_items).where(work_items.c.task_id == started.task_id)).mappings().one()
        require(current["state"] == "active" and current["version"] == started.version + 1
                and item["state"] == "blocked" and item["blocked_reason"] == "capability_not_enabled",
                "task_worker_did_not_persist_real_initial_block")
        require(probe.row(draft.task_id)["state"] == "cancelled", "task_cancel_depended_on_completion_evidence")
        _unknown_cancellation(probe)
        expect_rejection(lambda: probe.app.complete(probe.actor(), draft.task_id, probe.complete_request(draft.task_id),
                                                    idempotency_key=probe.key("cancelled-complete")), "completion_source_not_allowed")
        request, key = probe.cancel_request(started.task_id), probe.key("worker-cancel")
        accepted = probe.app.cancel(probe.actor(), started.task_id, request, idempotency_key=key)
        require(accepted.status_code == 202, "task_worker_cancel_not_accepted")
        probe.wait_workflow(accepted.body.workflow_id)
        require(probe.row(started.task_id)["state"] == "cancelled", "task_worker_control_not_cancelled")
        before = probe.snapshot(started.task_id)
        # The real worker committed first. Reinvoke the same domain step boundary
        # as after a lost checkpoint/receipt, without changing any DBOS internals.
        first_initial = probe.app.run_initial(started.command_id)
        require(probe.app.run_initial(started.command_id) == first_initial, "task_initial_business_replay_changed")
        first_control = probe.app.run_control(accepted.body.command_id)
        require(probe.app.run_control(accepted.body.command_id) == first_control, "task_control_business_replay_changed")
        require(probe.app.cancel(probe.actor(), started.task_id, request, idempotency_key=key) == accepted,
                "task_lost_cancel_receipt_not_original")
        require(probe.snapshot(started.task_id) == before and _step_records(probe, started.workflow_id) == 1
                and _step_records(probe, accepted.body.workflow_id) == 1, "task_business_step_replay_duplicated_effects")
        row = probe.row(started.task_id)
        expect_rejection(lambda: probe.app.start(probe.actor(), started.task_id, StartTaskRequest(
            expected_version=row["version"], expected_control_revision=row["control_revision"],
            expected_input_validity_revision=row["input_validity_revision"],
        ), idempotency_key=probe.key("cancelled-start")), "task_progress_closed")
        late = probe.app.invalidate_input(probe.actor(), started.task_id, InvalidateTaskInputRequest(
            expected_version=row["version"], expected_control_revision=row["control_revision"],
            expected_input_validity_revision=row["input_validity_revision"],
            change_ref=changed_source(probe), reason="synthetic_late_cancelled_fact",
        ), idempotency_key=probe.key("cancelled-late-fact"))
        require(late.body.outcome == "impact_archived" and probe.row(started.task_id) == row,
                "task_cancelled_late_fact_revived_progress")
    return {"real_worker_initial_persists_blocked": True, "real_worker_control_cancels_without_candidate": True,
            "revoked_desktop_session_does_not_cancel_recorded_work": True,
            "cancelled_completion_rejected_and_progress_closed": True,
            "business_step_replay_after_real_worker_is_once": True,
            "lost_cancel_receipt_returns_original_response": True, "cancelled_late_fact_archived_only": True,
            "unknown_physical_operation_keeps_cancellation_pending": True,
            "explicit_synthetic_closure_allows_control_reconciliation": True}
