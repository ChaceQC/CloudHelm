"""Offline B01b check: PYTHONPATH=. PYTHONUTF8=1 .venv/bin/python -B docs/acceptance/b01/verify_tool_timeline.py."""

from datetime import UTC, datetime
from hashlib import sha256
import json

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from modules.agent_runtime.task_queries import _tool_results


RAW_MARKERS = (
    "fixture-raw-call-argument",
    "fixture-raw-retry-input",
    "fixture-raw-retry-message",
    "fixture-raw-retry-parameter",
)
SESSION_ID = "fixture-b01-session"


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(raw):
    return "sha256:" + sha256(raw).hexdigest()


def run_record(run_id, start_digest, end_digest):
    return {
        "run_id": run_id,
        "session_id": SESSION_ID,
        "start_json": {
            "runtime_input": {"committed_history": {"digest": start_digest}},
            "context": {"tool_names": ["workspace.read_file", "await_operation"]},
            "policy": {"tool_protocol_revision": "named-r1"},
        },
        "result_json": {"turn": {"history_delta": {"digest": end_digest}}},
    }


def sdk_histories(operation_id):
    at = datetime(2026, 11, 19, tzinfo=UTC)
    invalid_path = {"text": RAW_MARKERS[1]}
    first = [
        ModelRequest(parts=[UserPromptPart("fixture prompt", timestamp=at)], timestamp=at, run_id="sdk-first"),
        ModelResponse(parts=[
            ToolCallPart("workspace_read_file", {"path": "fixture.txt"}, "fixture-read"),
            ToolCallPart(
                "workspace_read_file", {"path": invalid_path, "extra": RAW_MARKERS[0]}, "fixture-invalid",
            ),
            ToolCallPart("workspace_undeclared", {}, "fixture-undeclared"),
        ], timestamp=at, run_id="sdk-first"),
        ModelRequest(parts=[
            ToolReturnPart("workspace_read_file", {"text": "固定结果"}, "fixture-read", timestamp=at),
            RetryPromptPart(
                content=[{"type": "string_type", "loc": ("path",), "input": invalid_path,
                          "msg": RAW_MARKERS[2], "ctx": {"detail": RAW_MARKERS[3]}}],
                tool_name="workspace_read_file", tool_call_id="fixture-invalid", timestamp=at,
            ),
            ToolReturnPart("workspace_undeclared", "fixture undeclared result", "fixture-undeclared", timestamp=at),
        ], timestamp=at, run_id="sdk-first"),
        ModelResponse(parts=[
            ToolCallPart("await_operation", {"operation_id": operation_id}, "fixture-late"),
        ], timestamp=at, run_id="sdk-first"),
    ]
    # The return body omits identity; the timeline has the persisted wait for that.
    continued = [
        *first,
        ModelRequest(parts=[
            ToolReturnPart("await_operation", {"state": "registered"}, "fixture-late", timestamp=at),
        ], timestamp=at, run_id="sdk-second"),
    ]
    return first, continued


def main():
    original_run_id, continuation_run_id = "fixture-b01-original", "fixture-b01-continuation"
    operation_id = "fixture-b01-operation"
    first, continued = (
        canonical_json(json.loads(ModelMessagesTypeAdapter.dump_json(messages)))
        for messages in sdk_histories(operation_id)
    )
    first_digest, continued_digest = digest(first), digest(continued)
    histories = {(SESSION_ID, first_digest): json.loads(first), (SESSION_ID, continued_digest): json.loads(continued)}
    original_run = run_record(original_run_id, digest(b"[]"), first_digest)
    continuation_run = run_record(continuation_run_id, first_digest, continued_digest)
    wait = {"tool_call_id": "fixture-late", "from_run_id": original_run_id, "operation_id": operation_id}

    first_items, truncated = _tool_results(original_run, histories)
    assert not truncated
    assert [(row["kind"], row["tool_name"], row["tool_call_id"], row["call_run_id"], row["result"])
            for row in first_items] == [
        ("call", "await_operation", "fixture-late", original_run_id, None),
        ("retry", "workspace.read_file", "fixture-invalid", original_run_id, "tool_arguments_invalid"),
        ("return", "workspace.read_file", "fixture-read", original_run_id, {"text": "固定结果"}),
        ("call", "workspace.read_file", "fixture-invalid", original_run_id, None),
        ("call", "workspace.read_file", "fixture-read", original_run_id, None),
    ]
    assert all(row.get("operation_id") is None for row in first_items)

    assert _tool_results(continuation_run, histories, continuation_wait=wait) == ([{
        "kind": "return", "tool_name": "await_operation", "tool_call_id": "fixture-late",
        "call_run_id": original_run_id, "operation_id": operation_id, "result": {"state": "registered"},
    }], False)
    assert _tool_results(continuation_run, histories) == ([], False)

    projected = canonical_json(first_items)
    for marker in RAW_MARKERS:
        assert marker.encode("utf-8") in first and marker.encode("utf-8") not in projected
    for history_digest, before in ((first_digest, first), (continued_digest, continued)):
        after = canonical_json(histories[SESSION_ID, history_digest])
        assert after == before and digest(after) == history_digest
    print("B01b: fixed SDK tool timeline and committed history checks passed")


if __name__ == "__main__":
    main()
