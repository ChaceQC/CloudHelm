"""Actual command-path failures, including a real public DBOS enqueue before failure."""

from unittest.mock import patch

from sqlalchemy import event

from packages.contracts.p1.task_requests import StartTaskRequest
from scripts.p1.task_probe import require


class InjectedTaskFailure(RuntimeError):
    pass


def _statement_point(statement):
    text = statement.lstrip().lower()
    for prefix, name in (
        ("insert into cloudhelm.work_items", "business"),
        ("insert into cloudhelm.event_log", "event"),
        ("insert into cloudhelm.outbox", "outbox"),
        ("insert into cloudhelm.workflow_bindings", "binding"),
    ):
        if text.startswith(prefix):
            return name
    return None


def _one_fault(probe, point):
    created = probe.create("rollback-" + point)
    before = probe.snapshot(created.task_id)
    request = StartTaskRequest(expected_version=created.version, expected_control_revision=created.control_revision,
                               expected_input_validity_revision=created.input_validity_revision)
    actor, called, workflow_ids, injected = probe.actor(), [], [], []
    real_enqueue = probe.client.enqueue_in_transaction

    def enqueue(connection, options, *args, **kwargs):
        workflow_ids.append(options["workflow_id"])
        result = real_enqueue(connection, options, *args, **kwargs)
        called.append(True)
        if point == "enqueue":
            injected.append(point)
            raise InjectedTaskFailure("task_injected_after_real_enqueue")
        return result

    def after_sql(connection, cursor, statement, parameters, context, executemany):
        if _statement_point(statement) == point:
            injected.append(point)
            raise InjectedTaskFailure("task_injected_after_real_write")

    event.listen(probe.pools.normal, "after_cursor_execute", after_sql)
    try:
        with patch.object(probe.client, "enqueue_in_transaction", side_effect=enqueue):
            try:
                probe.app.start(actor, created.task_id, request, idempotency_key=probe.key("rollback"))
            except Exception:
                require(injected == [point], "task_fault_path_not_reached")
            else:
                require(False, "task_fault_not_injected")
    finally:
        event.remove(probe.pools.normal, "after_cursor_execute", after_sql)
    require(probe.snapshot(created.task_id) == before, "task_partial_transaction_committed")
    if point in {"event", "outbox", "enqueue"}:
        require(bool(called), "task_fault_did_not_call_real_sdk")
    for identity in workflow_ids:
        require(probe.workflow_status(identity) is None, "task_rolled_back_workflow_visible")


def run_fault_checks(probe):
    result = {}
    for point in ("business", "event", "outbox", "binding", "enqueue"):
        _one_fault(probe, point)
        result["atomic_rollback_after_" + point] = True
    return result
