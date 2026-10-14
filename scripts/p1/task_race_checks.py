"""Two independent control pools with bounded, real row-lock contention."""

from concurrent.futures import ThreadPoolExecutor
import threading

from sqlalchemy import event

from modules.collaboration.application import TaskApplication
from packages.contracts.p1.task_internal import InvalidateTaskInputRequest
from scripts.p1.task_completion_fixture import stage_completion
from scripts.p1.task_operation_fixture import changed_source, operation_reference, write_request
from scripts.p1.task_probe import require


def _race(first_engine, second_engine, first, second):
    first_locked, second_entered, release = threading.Event(), threading.Event(), threading.Event()

    def first_update(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("update cloudhelm.tasks"):
            first_locked.set()
            require(release.wait(10), "task_race_release_timeout")

    def second_lock(connection, cursor, statement, parameters, context, executemany):
        text = statement.lower()
        if "cloudhelm.users" in text and "for update" in text:
            second_entered.set()

    event.listen(first_engine, "before_cursor_execute", first_update)
    event.listen(second_engine, "before_cursor_execute", second_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            leading = executor.submit(first)
            try:
                require(first_locked.wait(10), "task_race_first_not_ready")
                following = executor.submit(second)
                require(second_entered.wait(10), "task_race_second_not_started")
                release.set()
                return leading.result(timeout=20), following.result(timeout=20)
            finally:
                release.set()
    finally:
        event.remove(first_engine, "before_cursor_execute", first_update)
        event.remove(second_engine, "before_cursor_execute", second_lock)


def _requests(probe, seeded, other):
    complete = probe.complete_request(seeded.task_id)
    if other == "cancel":
        return complete, probe.cancel_request(seeded.task_id)
    if other == "input":
        return complete, InvalidateTaskInputRequest(
            expected_version=complete.expected_version, expected_control_revision=complete.expected_control_revision,
            expected_input_validity_revision=complete.expected_input_validity_revision,
            change_ref=changed_source(probe), reason="synthetic_concurrent_input",
        )
    if other == "write":
        reference = operation_reference(probe, seeded, label="race")
        return complete, write_request(probe, seeded, reference)
    return complete, complete


def _pair(probe, other, completion_first):
    seeded = stage_completion(probe)
    completion, contender = _requests(probe, seeded, other)
    actor = probe.actor()
    # All contenders in this verifier use two distinct reserved control engines.
    first_app = TaskApplication(probe.pools.control, probe.pools.control, probe.client)
    second_app = TaskApplication(probe.other_control, probe.other_control, probe.client)
    first_key, second_key = probe.key("race-first"), probe.key("race-second")
    method = {"complete": "complete", "cancel": "cancel", "input": "invalidate_input", "write": "register_write_intent"}[other]
    if completion_first:
        first = lambda: first_app.complete(actor, seeded.task_id, completion, idempotency_key=first_key)
        second = lambda: getattr(second_app, method)(actor, seeded.task_id, contender, idempotency_key=second_key)
    else:
        first = lambda: getattr(first_app, method)(actor, seeded.task_id, contender, idempotency_key=first_key)
        second = lambda: second_app.complete(actor, seeded.task_id, completion, idempotency_key=second_key)
    leading, following = _race(probe.pools.control, probe.other_control, first, second)
    row, counts = probe.snapshot(seeded.task_id)
    if completion_first:
        require(leading.status_code == 200 and leading.body.outcome == "completed"
                and row["state"] == "completed" and counts["reports"] == 1, "task_completion_race_lost_fixed_report")
        if other in {"complete", "cancel"}:
            require(following.status_code == 200 and following.body.outcome == "already_completed"
                    and following.body.completion_report_id == leading.body.completion_report_id,
                    "task_race_did_not_return_original_report")
        elif other == "input":
            require(following.status_code == 200 and following.body.outcome == "impact_archived"
                    and row["input_validity_revision"] == completion.expected_input_validity_revision,
                    "task_losing_input_rewrote_report")
        else:
            require(following.status_code == 409 and row["operation_set_revision"] == 0,
                    "task_losing_write_was_admitted")
    else:
        require(following.status_code == 409 and counts["reports"] == 0 and row["state"] != "completed",
                "task_stale_completion_won_race")
        if other == "cancel":
            require(leading.status_code == 202 and row["cancel_requested_at"] is not None
                    and row["ordinary_progress_closed"], "task_cancel_race_not_fenced")
        elif other == "input":
            require(leading.status_code == 200 and row["input_status"] == "needs_review"
                    and row["input_validity_revision"] == completion.expected_input_validity_revision + 1,
                    "task_input_race_not_invalidated")
        else:
            require(leading.status_code == 200 and row["operation_set_revision"] == 1
                    and row["input_validity_revision"] == completion.expected_input_validity_revision,
                    "task_write_race_missing_intent")


def run_race_checks(probe):
    _pair(probe, "complete", True)
    checks = {"concurrent_completion_unique_report": True}
    for other in ("cancel", "input", "write"):
        _pair(probe, other, True)
        _pair(probe, other, False)
        checks[f"completion_wins_{other}_race"] = True
        checks[f"{other}_wins_completion_race"] = True
    return checks
