"""Interpret the committed SDK history for one Agent Run."""

from hashlib import sha256

from pydantic_ai.messages import ModelMessagesTypeAdapter, RetryPromptPart, ToolCallPart, ToolReturnPart

from packages.contracts.p2.tool_protocol import (
    DISPATCH_TOOL_PROTOCOL_REVISION, NAMED_TOOL_ACTIONS, NAMED_TOOL_PROTOCOLS,
)


_EMPTY_HISTORY = "sha256:" + sha256(b"[]").hexdigest()


def _tool_protocol_revision(run):
    return run["start_json"]["policy"].get("tool_protocol_revision", DISPATCH_TOOL_PROTOCOL_REVISION)


def _tool_history_boundaries(run):
    result = run["result_json"]
    if result is None or _tool_protocol_revision(run) not in (DISPATCH_TOOL_PROTOCOL_REVISION, *NAMED_TOOL_PROTOCOLS):
        return ()
    start = run["start_json"]["runtime_input"]["committed_history"]["digest"]
    end = result["turn"]["history_delta"]["digest"]
    return (start, end) if start != end else ()


def _tool_history_messages(session_id, boundaries, histories):
    start, end = boundaries
    previous = [] if start == _EMPTY_HISTORY else histories.get((session_id, start))
    history = histories.get((session_id, end))
    if previous is None or history is None or history[:len(previous)] != previous:
        return [], 0, True
    return ModelMessagesTypeAdapter.validate_python(history), len(previous), False


def _tool_call_events(run_id, messages, previous_count, permitted, continuation_wait, *, dispatch=False):
    pending, results = {}, []
    for index, message in enumerate(messages):
        in_prefix = index < previous_count
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                # Only the fixed wait may carry a pending call from the committed prefix.
                if in_prefix and (continuation_wait is None or part.tool_call_id != continuation_wait["tool_call_id"]):
                    continue
                if dispatch:
                    if part.tool_name != "dispatch_tool":
                        continue
                    requested = part.args_as_dict().get("name")
                    action = requested if isinstance(requested, str) and requested in permitted else "dispatch_tool"
                else:
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
                results.append(entry)
    return results
