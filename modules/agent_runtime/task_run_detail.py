"""Read a single owned Run and project its bounded public facts."""

from sqlalchemy import and_, func, select

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.tables import task_wait_conditions
from packages.contracts.p2.task_agent import TaskAgentRunDetail
from packages.contracts.p2.tool_protocol import DISPATCH_TOOL_PROTOCOL_REVISION
from .billing_tables import agent_model_request_results
from .operation_tables import agent_operation_waits
from .tables import agent_histories, agent_model_requests, agent_runs, agent_sessions
from .task_queries import (
    _EMPTY_HISTORY, _tool_call_events, _tool_history_boundaries, _tool_history_messages, _tool_protocol_revision,
)


_TOOL_LIMIT = 16
_REQUEST_LIMIT = 12
_WAIT_LIMIT = 8
_OPERATION_LIMIT = 24
_EVIDENCE_LIMIT = 8

_OPERATION_TOOLS = {
    "submit_operation", "query_operation", "await_operation", "workspace.create_file", "workspace.apply_patch",
    "workspace.submit_candidate", "workspace.prepare_environment", "workspace.control_environment", "build.request",
}
_RESULT_SUMMARIES = {
    "accepted": "operation_accepted", "registered": "operation_result_registered", "rejected": "tool_request_rejected",
    "unknown": "tool_result_unknown", "running": "operation_running", "succeeded": "operation_succeeded",
    "failed": "operation_failed",
}


def _read_waits(connection, task_id, run, deferred_result):
    waits, conditions = agent_operation_waits, task_wait_conditions
    scope = waits.c.from_run_id == run["run_id"]
    ordering = [waits.c.wait_condition_id.desc()]
    if deferred_result is not None:
        incoming = and_(waits.c.continuation_run_id == run["run_id"],
                        waits.c.wait_condition_id == deferred_result["object_id"])
        scope = scope | incoming
        # Keep the exact continuation wait even if the outgoing wait list fills its limit.
        ordering.insert(0, incoming.desc())
    return connection.execute(select(
        waits.c.wait_condition_id, waits.c.from_run_id, waits.c.tool_call_id, waits.c.operation_id,
        waits.c.continuation_run_id, conditions.c.state, conditions.c.required_for_completion,
    ).select_from(waits.join(conditions)).where(
        scope, waits.c.session_id == run["session_id"], conditions.c.task_id == task_id,
    ).order_by(*ordering).limit(_WAIT_LIMIT + 1)).mappings().all()


def _read_requests(connection, run_id):
    requests, observations = agent_model_requests, agent_model_request_results
    latest = select(func.max(observations.c.revision)).where(
        observations.c.request_record_id == requests.c.request_record_id,
    ).correlate(requests).scalar_subquery()
    rows = connection.execute(select(
        requests.c.request_record_id, requests.c.reserved_cost, observations.c.calculated_cost,
        observations.c.billed_amount, observations.c.billed_currency,
        observations.c.revision.label("observation_revision"), observations.c.reconciliation_evidence_ref,
    ).select_from(requests.outerjoin(observations, and_(
        observations.c.request_record_id == requests.c.request_record_id, observations.c.revision == latest,
    ))).where(requests.c.run_id == run_id).order_by(requests.c.request_sequence.desc()).limit(
        _REQUEST_LIMIT + 1)).mappings().all()
    return [{
        **row, "state": "observed" if row["observation_revision"] is not None else "unknown",
        "reserved_cost": format(row["reserved_cost"], "f"),
        "calculated_cost": format(row["calculated_cost"], "f") if row["calculated_cost"] is not None else None,
        "billed_amount": format(row["billed_amount"], "f") if row["billed_amount"] is not None else None,
    } for row in rows[:_REQUEST_LIMIT]], len(rows) > _REQUEST_LIMIT


def _tool_return_summary(tool, value):
    if not isinstance(value, dict):
        return "tool_result_recorded", None
    # Only these Gateway routes return authoritative operation references at these paths.
    operation = value if tool in _OPERATION_TOOLS else None
    if tool in {"build.result", "review.evidence"}:
        operation = value.get("build")
    operation_id = operation.get("operation_id") if isinstance(operation, dict) else None
    state_source = operation if isinstance(operation, dict) else value
    status = state_source.get("status") or state_source.get("state")
    summary = _RESULT_SUMMARIES.get(status, "tool_result_recorded") if isinstance(status, str) else "tool_result_recorded"
    return summary, operation_id if isinstance(operation_id, str) and 1 <= len(operation_id) <= 160 else None


def _read_tool_timeline(connection, run, waits, continuation_wait):
    boundaries = _tool_history_boundaries(run)
    if not boundaries:
        return [], [], False
    session_id = run["session_id"]
    rows = connection.execute(select(agent_histories.c.history_key, agent_histories.c.value_json).where(
        agent_histories.c.session_id == session_id,
        agent_histories.c.history_key.in_([key for key in boundaries if key != _EMPTY_HISTORY]),
    )).mappings()
    histories = {(session_id, row["history_key"]): row["value_json"] for row in rows}
    messages, previous_count, incomplete = _tool_history_messages(session_id, boundaries, histories)
    permitted = set(run["start_json"]["context"]["tool_names"])
    calls = _tool_call_events(run["run_id"], messages, previous_count, permitted, continuation_wait,
                              dispatch=_tool_protocol_revision(run) == DISPATCH_TOOL_PROTOCOL_REVISION)
    by_call = {(wait["from_run_id"], wait["tool_call_id"]): wait["operation_id"] for wait in waits}
    events, operation_ids = [], []
    for call in reversed(calls):
        kind, tool_call_id = call["kind"], call["tool_call_id"]
        if not 1 <= len(tool_call_id) <= 160:
            incomplete = True
            continue
        operation_id = by_call.get((call["call_run_id"], tool_call_id))
        summary = None
        if kind == "return":
            summary, result_operation = _tool_return_summary(call["tool_name"], call["result"])
            operation_id = operation_id or result_operation
        elif kind == "retry":
            summary = call["result"]
        if operation_id is not None:
            operation_ids.append(operation_id)
        if len(events) == _TOOL_LIMIT:
            incomplete = True
            continue
        events.append({"kind": kind, "tool_call_id": tool_call_id, "tool_name": call["tool_name"],
                       "call_run_id": call["call_run_id"], "operation_id": operation_id, "summary": summary})
    return events, operation_ids, incomplete


def query_agent_run_in_uow(uow, task, run_id):
    """The caller checks current Task and Operation read grants in this transaction."""
    connection, task_id = uow.connection, task["task_id"]
    run = connection.execute(select(agent_runs).join(agent_sessions).where(
        agent_runs.c.run_id == run_id, agent_sessions.c.task_id == task_id,
    )).mappings().one_or_none()
    if run is None:
        raise TaskBoundaryError("agent_run_not_found", status_code=404)

    start, result = run["start_json"], run["result_json"] or {}
    incoming, context = start["runtime_input"], start["context"]
    turn = result.get("turn", {})
    deferred_result = incoming.get("deferred_results")
    waits = _read_waits(connection, task_id, run, deferred_result)
    continuation_wait = None
    if deferred_result is not None:
        continuation_wait = next((wait for wait in waits if wait["wait_condition_id"] == deferred_result["object_id"]
                                  and wait["continuation_run_id"] == run_id), None)
    events, tool_operations, timeline_truncated = _read_tool_timeline(
        connection, run, waits[:_WAIT_LIMIT], continuation_wait)
    requests, requests_truncated = _read_requests(connection, run_id)

    evidence = turn.get("delivery_refs", ())
    # Resolved handoff facts are written by the Runtime after checking domain ownership and applicability.
    handoff = result.get("handoff", {}) if evidence else {}
    candidate, review = handoff.get("candidate", {}), handoff.get("review") or {}
    operations = tuple(dict.fromkeys(operation_id for operation_id in (
        *(wait["operation_id"] for wait in waits[:_WAIT_LIMIT]),
        candidate.get("freeze_operation_id"), review.get("build_operation_id"), *tool_operations,
    ) if operation_id is not None))
    return TaskAgentRunDetail(
        task_id=task_id, session_id=run["session_id"], run_id=run_id, work_item_id=context["work_item_id"],
        work_item_revision=context["work_item_revision"], state=run["state"], request_count=run["request_count"],
        reserved_cost=format(run["reserved_cost"], "f"), created_at=run["created_at"],
        started_at=run["started_at"], deadline_at=run["deadline_at"], tool_protocol_revision=_tool_protocol_revision(run),
        reason_code=turn.get("reason_code"), outcome=turn.get("outcome"), input_set_ref=incoming["input_set"],
        tool_timeline=events, requests=requests, waits=waits[:_WAIT_LIMIT], operation_ids=operations[:_OPERATION_LIMIT],
        evidence_refs=evidence[:_EVIDENCE_LIMIT], verification_report_id=(
            handoff.get("verification", {}).get("report_id") or review.get("verification_report_id")),
        truncated=(timeline_truncated or requests_truncated or len(waits) > _WAIT_LIMIT
                   or len(operations) > _OPERATION_LIMIT or len(evidence) > _EVIDENCE_LIMIT),
    )
