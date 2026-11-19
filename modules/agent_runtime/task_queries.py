"""Bounded Task view of persisted Agent runs; the caller authorizes the Task."""

from hashlib import sha256
import json

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter, ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart,
)
from sqlalchemy import and_, func, select, tuple_

from modules.collaboration.tables import task_wait_conditions
from packages.contracts.p2.tool_protocol import (
    DISPATCH_TOOL_PROTOCOL_REVISION, NAMED_TOOL_ACTIONS, NAMED_TOOL_PROTOCOLS,
)
from .billing_tables import agent_model_request_results
from .context import safe_context_value
from .operation_tables import agent_operation_waits
from .tables import agent_histories, agent_model_requests, agent_runs, agent_sessions


_EMPTY_HISTORY = "sha256:" + sha256(b"[]").hexdigest()
_TEXT_LIMIT = 4096


def _bounded_value(value):
    """Filter free text and secret-named fields before limiting response text."""
    truncated = False

    def visit(item):
        nonlocal truncated
        if isinstance(item, str):
            if len(item) > _TEXT_LIMIT:
                truncated = True
                return item[:_TEXT_LIMIT]
            return item
        if isinstance(item, dict):
            result = {}
            for key, value in item.items():
                marker = f"{key}: value"
                result[key] = "[REDACTED]" if safe_context_value(marker) != marker else visit(value)
            return result
        if isinstance(item, list):
            return [visit(value) for value in item]
        return item

    return visit(safe_context_value(value)), truncated


def _tool_protocol_revision(run):
    return run["start_json"]["policy"].get("tool_protocol_revision", DISPATCH_TOOL_PROTOCOL_REVISION)


def _tool_results(run, histories, continuation_wait=None):
    result = run["result_json"]
    if result is None:
        return [], False
    revision = _tool_protocol_revision(run)
    if revision != DISPATCH_TOOL_PROTOCOL_REVISION and revision not in NAMED_TOOL_PROTOCOLS:
        return [], False
    start = run["start_json"]["runtime_input"]["committed_history"]["digest"]
    end = result["turn"]["history_delta"]["digest"]
    if start == end:
        return [], False
    session_id = run["session_id"]
    previous = [] if start == _EMPTY_HISTORY else histories.get((session_id, start))
    history = histories.get((session_id, end))
    if previous is None or history is None or history[:len(previous)] != previous:
        return [], True

    messages = ModelMessagesTypeAdapter.validate_python(history)
    permitted = set(run["start_json"]["context"]["tool_names"])
    if revision in NAMED_TOOL_PROTOCOLS:
        results = _named_tool_results(run["run_id"], messages, len(previous), permitted, continuation_wait)
    else:
        results = _dispatch_tool_results(messages, len(previous), permitted)
    limited, text_truncated = _bounded_value(list(reversed(results[-16:])))
    return limited, text_truncated or len(results) > 16


def _dispatch_tool_results(messages, previous_count, permitted):
    names = {}
    for message in messages:
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart) and part.tool_name == "dispatch_tool":
                    name = part.args_as_dict().get("name")
                    if isinstance(name, str) and name in permitted:
                        names[part.tool_call_id] = name

    results = []
    for message in messages[previous_count:]:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if not isinstance(part, (ToolReturnPart, RetryPromptPart)) or part.tool_name != "dispatch_tool":
                    continue
                content = part.content
                if isinstance(part, RetryPromptPart) and isinstance(content, list):
                    # Validation errors can contain the model's original arguments in `input`.
                    content = [{key: error[key] for key in ("type", "loc", "msg") if key in error}
                               for error in content]
                results.append({"tool_call_id": part.tool_call_id,
                                "tool_name": names.get(part.tool_call_id, "dispatch_tool"),
                                "result": content})
    return results


def _named_tool_results(run_id, messages, previous_count, permitted, continuation_wait):
    pending, results = {}, []
    for index, message in enumerate(messages):
        in_prefix = index < previous_count
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                # Only the fixed wait may carry a pending call from the committed prefix.
                if in_prefix and (continuation_wait is None or part.tool_call_id != continuation_wait["tool_call_id"]):
                    continue
                action = NAMED_TOOL_ACTIONS.get(part.tool_name)
                if action not in permitted:
                    pending.pop(part.tool_call_id, None)
                    continue
                origin = continuation_wait["from_run_id"] if in_prefix else run_id
                pending[part.tool_call_id] = (part.tool_name, action, origin)
                if not in_prefix:
                    results.append({"kind": "call", "tool_call_id": part.tool_call_id,
                                    "tool_name": action, "call_run_id": origin, "result": None})
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                call = pending.get(part.tool_call_id)
                if call is None or call[0] != part.tool_name:
                    continue
                del pending[part.tool_call_id]
                if in_prefix:
                    continue
                _, action, origin = call
                entry = {"tool_call_id": part.tool_call_id, "tool_name": action, "call_run_id": origin}
                if isinstance(part, RetryPromptPart):
                    code = "tool_arguments_invalid" if isinstance(part.content, list) else "tool_retry_requested"
                    entry.update(kind="retry", result=code)
                else:
                    entry.update(kind="return", result=part.content)
                    if origin != run_id:
                        entry["operation_id"] = continuation_wait["operation_id"]
                    elif isinstance(part.content, dict) and isinstance(part.content.get("operation_id"), str):
                        entry["operation_id"] = part.content["operation_id"]
                results.append(entry)
    return results


def query_agent_in_uow(uow, task):
    """Read only persisted facts; Task and operation access are checked by the caller."""
    connection = uow.connection
    sessions = connection.execute(select(agent_sessions).where(
        agent_sessions.c.task_id == task["task_id"],
    ).order_by(agent_sessions.c.created_at.desc(), agent_sessions.c.session_id.desc()).limit(9)).mappings().all()
    truncated = len(sessions) > 8
    sessions = sessions[:8]
    runs_by_session = {}
    runs = []
    history_keys = set()
    for session in sessions:
        rows = connection.execute(select(agent_runs).where(
            agent_runs.c.session_id == session["session_id"],
        ).order_by(agent_runs.c.created_at.desc(), agent_runs.c.run_id.desc()).limit(9)).mappings().all()
        truncated |= len(rows) > 8
        rows = rows[:8]
        runs_by_session[session["session_id"]] = rows
        runs.extend(rows)
        for row in rows:
            if row["result_json"] is not None:
                start = row["start_json"]["runtime_input"]["committed_history"]["digest"]
                end = row["result_json"]["turn"]["history_delta"]["digest"]
                if start != end:
                    if start != _EMPTY_HISTORY:
                        history_keys.add((session["session_id"], start))
                    history_keys.add((session["session_id"], end))

    histories = {}
    if history_keys:
        history_rows = connection.execute(select(
            agent_histories.c.session_id, agent_histories.c.history_key, agent_histories.c.value_json,
        ).where(tuple_(agent_histories.c.session_id, agent_histories.c.history_key).in_(history_keys))).mappings()
        histories = {(row["session_id"], row["history_key"]): row["value_json"] for row in history_rows}

    requests_by_run = {row["run_id"]: [] for row in runs}
    waits_by_run = {row["run_id"]: [] for row in runs}
    continuation_waits = {}
    if runs:
        run_ids = list(requests_by_run)
        latest_revision = select(func.max(agent_model_request_results.c.revision)).where(
            agent_model_request_results.c.request_record_id == agent_model_requests.c.request_record_id,
        ).correlate(agent_model_requests).scalar_subquery()
        request_rows = connection.execute(select(
            agent_model_requests.c.run_id, agent_model_requests.c.request_record_id,
            agent_model_requests.c.reserved_cost,
            agent_model_request_results.c.revision.label("observation_revision"),
            agent_model_request_results.c.calculated_cost, agent_model_request_results.c.billed_amount,
            agent_model_request_results.c.billed_currency,
        ).select_from(agent_model_requests.outerjoin(agent_model_request_results, and_(
            agent_model_request_results.c.request_record_id == agent_model_requests.c.request_record_id,
            agent_model_request_results.c.revision == latest_revision,
        ))).where(agent_model_requests.c.run_id.in_(run_ids)).order_by(
            agent_model_requests.c.created_at.desc(), agent_model_requests.c.request_record_id.desc(),
        )).mappings()
        for row in request_rows:
            items = requests_by_run[row["run_id"]]
            if len(items) == 12:
                truncated = True
                continue
            items.append({"request_record_id": row["request_record_id"],
                          "state": "observed" if row["observation_revision"] is not None else "unknown",
                          "reserved_cost": str(row["reserved_cost"]),
                          "calculated_cost": str(row["calculated_cost"]) if row["calculated_cost"] is not None else None,
                          "billed_amount": str(row["billed_amount"]) if row["billed_amount"] is not None else None,
                          "billed_currency": row["billed_currency"]})

        continuation_keys = {
            (row["session_id"], row["run_id"], reference["object_id"]) for row in runs
            if _tool_protocol_revision(row) in NAMED_TOOL_PROTOCOLS
            and (reference := row["start_json"]["runtime_input"].get("deferred_results")) is not None
        }
        wait_scope = agent_operation_waits.c.from_run_id.in_(run_ids)
        if continuation_keys:
            wait_scope |= tuple_(agent_operation_waits.c.session_id, agent_operation_waits.c.continuation_run_id,
                                 agent_operation_waits.c.wait_condition_id).in_(continuation_keys)
        wait_rows = connection.execute(select(
            agent_operation_waits.c.from_run_id, agent_operation_waits.c.wait_condition_id,
            agent_operation_waits.c.operation_id, task_wait_conditions.c.state,
            agent_operation_waits.c.continuation_run_id, agent_operation_waits.c.session_id,
            agent_operation_waits.c.tool_call_id,
        ).select_from(agent_operation_waits.join(task_wait_conditions)).where(
            wait_scope, task_wait_conditions.c.task_id == task["task_id"],
        ).order_by(agent_operation_waits.c.wait_condition_id.desc())).mappings()
        for row in wait_rows:
            continuation = row["continuation_run_id"]
            if (row["session_id"], continuation, row["wait_condition_id"]) in continuation_keys:
                continuation_waits[continuation] = row
            items = waits_by_run.get(row["from_run_id"])
            if items is None:
                continue
            if len(items) == 8:
                truncated = True
                continue
            items.append({key: row[key] for key in (
                "wait_condition_id", "operation_id", "state", "continuation_run_id")})

    views, response_bytes = [], 0
    for session in sessions:
        rows = runs_by_session[session["session_id"]]
        if not rows:
            continue
        latest = rows[0]["start_json"]
        policy = latest["policy"]
        run_views = []
        for row in rows:
            result, result_truncated = _bounded_value(row["result_json"])
            tools, tools_truncated = _tool_results(row, histories, continuation_waits.get(row["run_id"]))
            truncated |= result_truncated or tools_truncated
            run_view = {
                "run_id": row["run_id"], "state": row["state"], "request_count": row["request_count"],
                "reserved_cost": str(row["reserved_cost"]), "created_at": row["created_at"].isoformat(),
                "started_at": row["started_at"].isoformat() if row["started_at"] is not None else None,
                "deadline_at": row["deadline_at"].isoformat() if row["deadline_at"] is not None else None,
                "tool_protocol_revision": _tool_protocol_revision(row),
                "result": result, "tool_results": tools, "requests": requests_by_run[row["run_id"]],
                "waits": waits_by_run[row["run_id"]],
            }
            size = len(json.dumps(run_view, ensure_ascii=False).encode("utf-8"))
            if response_bytes + size > 512 * 1024:
                truncated = True
                break
            response_bytes += size
            run_views.append(run_view)
        views.append({
            "session_id": session["session_id"], "version": session["version"], "state": session["state"],
            "work_item_id": latest["context"]["work_item_id"],
            "policy": {"max_requests": policy["max_requests"],
                       "max_duration_seconds": policy["max_duration_seconds"],
                       "max_output_tokens": policy["max_output_tokens"],
                       "per_request_cost_upper_bound": str(policy["per_request_cost_upper_bound"])},
            "runs": run_views,
        })
    return {"task_id": task["task_id"], "sessions": views, "truncated": truncated}
