"""Run the isolated PydanticAI/Gateway protocol probe for SDK-03 and SDK-04."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
from importlib.metadata import version
from typing import Any, AsyncIterable, Iterable

from dbos import DBOS
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ExternalToolset
from pydantic_ai.messages import (
    AgentStreamEvent,
    DeferredToolRequestsEvent,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import RunContext, ToolDefinition

from gateway_probe import (
    CurrentGate,
    Gateway,
    GatewayProbeError,
    GateDenied,
    canonical_json,
    operation_identity,
    request_digest,
)

PROBE_ID = "sdk03-04-fixed-input-v1"
OPERATION_KEY = "sdk04/durable-submit-v1"
OPERATION_ARGS = {"counter_delta": 1, "fixture": "p0-sdk03-04"}
RESULT_ID = "sdk04/result-v1"
RESULT_PAYLOAD = {"artifact_ref": "p0://sdk04/fixed-result-v1", "outcome": "succeeded"}
DBOS_SCHEMA = "p0_sdk04_dbos"
DBOS_APP_NAME = "cloudhelm-p0-sdk03-04"
CRASH_AFTER_STEP = os.environ.get("CLOUDHELM_P0_CRASH_AFTER_STEP") == "1"
STEP_RETURNED = threading.Event()
ALLOW_CRASH = threading.Event()
CRASH_EXIT_CODE = 75


class ProtocolProbeError(RuntimeError):
    """A fixed SDK seam expectation was not met."""


class MixedBatchRejected(ProtocolProbeError):
    """Query, long submit and wait calls must be separated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolProbeError(message)


def tool_definitions(names: Iterable[str]) -> list[ToolDefinition]:
    schemas = {
        "query_counter": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "submit_operation": {
            "type": "object",
            "properties": {
                "counter_delta": {"type": "integer"},
                "fixture": {"type": "string"},
            },
            "required": ["counter_delta", "fixture"],
            "additionalProperties": False,
        },
        "await_operation": {
            "type": "object",
            "properties": {"operation_id": {"type": "string"}},
            "required": ["operation_id"],
            "additionalProperties": False,
        },
    }
    return [
        ToolDefinition(
            name=name,
            description=f"Isolated P0 Gateway tool: {name}",
            parameters_json_schema=schemas[name],
        )
        for name in names
    ]


def tool_call(name: str, call_id: str, args: dict[str, Any] | None = None) -> ToolCallPart:
    return ToolCallPart(tool_name=name, args=args or {}, tool_call_id=call_id)


def classify_batch(calls: Iterable[ToolCallPart]) -> str:
    categories = {
        "query_counter": "query",
        "submit_operation": "submit",
        "await_operation": "wait",
    }
    requested = [categories.get(call.tool_name, "unsupported") for call in calls]
    if not requested or "unsupported" in requested:
        raise ProtocolProbeError("tool batch contains an unsupported probe tool")
    if len(set(requested)) != 1:
        raise MixedBatchRejected("query, long submit and wait calls require separate batches")
    return requested[0]


def complete_results(
    requests: DeferredToolRequests, values: dict[str, Any]
) -> DeferredToolResults:
    expected = {call.tool_call_id for call in requests.calls}
    require(set(values) == expected, "deferred result set is not complete")
    results = requests.build_results(calls=values)
    require(requests.remaining(results) is None, "PydanticAI still reports unresolved calls")
    require(
        set(results.to_tool_call_results()) == expected,
        "PydanticAI result conversion lost a tool-call identity",
    )
    return results


def validate_history(history: list[ModelMessage]) -> list[ModelMessage]:
    return ModelMessagesTypeAdapter.validate_python(history)


def make_controlled_agent(calls: list[ToolCallPart]) -> Agent[Any, Any]:
    names = sorted({call.tool_name for call in calls})

    def response_function(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("controlled PydanticAI continuation")])

    async def stream_function(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterable[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield {
            index: DeltaToolCall(
                name=call.tool_name,
                json_args=canonical_json(call.args_as_dict()),
                tool_call_id=call.tool_call_id,
            )
            for index, call in enumerate(calls)
        }

    return Agent(
        model=FunctionModel(
            response_function,
            stream_function=stream_function,
            model_name="cloudhelm-p0-function-model",
        ),
        output_type=[str, DeferredToolRequests],
        toolsets=[ExternalToolset(tool_definitions(names), id="p0-gateway-probe")],
        name="cloudhelm_p0_protocol_probe",
    )


async def run_streamed_agent(
    agent: Agent[Any, Any],
    prompt: str,
    *,
    run_id: str,
    event_handler: Any,
    message_history: list[ModelMessage] | None = None,
) -> Any:
    return await agent.run(
        prompt,
        message_history=message_history,
        run_id=run_id,
        event_stream_handler=event_handler,
    )


def submit_callback(
    gateway: Gateway, call: ToolCallPart, *, policy_revision: str
) -> tuple[dict[str, Any], bool]:
    return gateway.submit_operation(
        idempotency_key=OPERATION_KEY,
        tool_call_id=call.tool_call_id,
        args=OPERATION_ARGS,
        policy_revision=policy_revision,
    )


def _dbos_config() -> dict[str, Any]:
    return {
        "name": DBOS_APP_NAME,
        "application_version": "p0-sdk03-04-probe-v1",
        "system_database_url": (
            "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
        ),
        "dbos_system_schema": DBOS_SCHEMA,
        "log_level": "ERROR",
        "console_log_level": "ERROR",
        "run_migrations": True,
    }


@DBOS.step(name="sdk04.gateway_submit_and_complete")
def _gateway_submit_and_complete(
    agent_run_id: str,
    operation_key: str,
    tool_call_id: str,
    policy_revision: str,
) -> dict[str, Any]:
    gateway = Gateway(PROBE_ID, CurrentGate(revision=policy_revision))
    receipt, created = gateway.submit_operation(
        idempotency_key=operation_key,
        tool_call_id=tool_call_id,
        args=OPERATION_ARGS,
        policy_revision=policy_revision,
    )
    operation_id = operation_identity(PROBE_ID, operation_key)
    digest = request_digest("submit_operation", OPERATION_ARGS)
    final_result, applied = gateway.complete_operation(
        operation_id=operation_id,
        expected_digest=digest,
        result_id=RESULT_ID,
        result=RESULT_PAYLOAD,
        policy_revision=policy_revision,
    )
    return {
        "agent_run_id": agent_run_id,
        "accepted_receipt": receipt,
        "submit_created_operation": created,
        "final_result": final_result,
        "effect_applied": applied,
    }


@DBOS.workflow(name="sdk04.original_agent_run")
def _original_agent_run(
    agent_run_id: str,
    operation_key: str,
    tool_call_id: str,
    policy_revision: str,
    history_json: str,
) -> dict[str, Any]:
    step_result = _gateway_submit_and_complete(
        agent_run_id, operation_key, tool_call_id, policy_revision
    )
    if CRASH_AFTER_STEP:
        STEP_RETURNED.set()
        if not ALLOW_CRASH.wait(timeout=20):
            raise TimeoutError("post-step crash injection was not released")
        os._exit(CRASH_EXIT_CODE)
    history = ModelMessagesTypeAdapter.validate_json(history_json)
    return {**step_result, "validated_history_messages": len(history)}


@DBOS.step(name="sdk04.gateway_await_result")
def _gateway_await_result(
    operation_id: str, expected_digest: str, policy_revision: str
) -> dict[str, Any] | None:
    gateway = Gateway(PROBE_ID, CurrentGate(revision=policy_revision))
    return gateway.await_operation(
        operation_id=operation_id,
        expected_digest=expected_digest,
        policy_revision=policy_revision,
    )


@DBOS.workflow(name="sdk04.continuation_agent_run")
def _continuation_agent_run(
    agent_run_id: str,
    operation_id: str,
    expected_digest: str,
    policy_revision: str,
    history_json: str,
    wait_call_id: str,
) -> dict[str, Any]:
    final_result = _gateway_await_result(operation_id, expected_digest, policy_revision)
    if final_result is None:
        return {"agent_run_id": agent_run_id, "outcome": "waiting"}
    history = ModelMessagesTypeAdapter.validate_json(history_json)
    history.extend(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="await_operation",
                        tool_call_id=wait_call_id,
                        content=canonical_json(final_result),
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content="operation result recorded")]),
        ]
    )
    validated = ModelMessagesTypeAdapter.validate_python(history)
    return {
        "agent_run_id": agent_run_id,
        "outcome": "result",
        "final_result": final_result,
        "validated_history_messages": len(validated),
    }


def _dbos_child(stage: str, workflow_id: str | None = None) -> int:
    DBOS(config=_dbos_config())
    DBOS.launch()
    if stage == "crash":
        handle = DBOS.start_workflow(
            _original_agent_run,
            os.environ["CLOUDHELM_P0_ORIGINAL_RUN_ID"],
            OPERATION_KEY,
            os.environ["CLOUDHELM_P0_TOOL_CALL_ID"],
            os.environ["CLOUDHELM_P0_POLICY_REVISION"],
            os.environ["CLOUDHELM_P0_ORIGINAL_HISTORY_JSON"],
        )
        print(f"WORKFLOW_ID={handle.get_workflow_id()}", flush=True)
        if not STEP_RETURNED.wait(timeout=30):
            DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=1)
            return 76
        ALLOW_CRASH.set()
        threading.Event().wait(timeout=30)
        DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=1)
        return 77

    if stage != "recover" or workflow_id is None:
        DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=1)
        return 78
    try:
        original_handle = DBOS.retrieve_workflow(workflow_id)
        original_result = original_handle.get_result()
        recovered_status = str(DBOS.get_workflow_status(workflow_id))
        operation_id = operation_identity(PROBE_ID, OPERATION_KEY)
        expected_digest = request_digest("submit_operation", OPERATION_ARGS)
        continuation = DBOS.start_workflow(
            _continuation_agent_run,
            "agent-run-sdk04-after-wait",
            operation_id,
            expected_digest,
            os.environ["CLOUDHELM_P0_POLICY_REVISION"],
            os.environ["CLOUDHELM_P0_CONTINUATION_HISTORY_JSON"],
            os.environ["CLOUDHELM_P0_WAIT_CALL_ID"],
        )
        continuation_result = continuation.get_result()
        continuation_id = continuation.get_workflow_id()
        same_workflow = original_handle.get_workflow_id() == workflow_id
        distinct_workflows = continuation_id != workflow_id
        DBOS.delete_workflows([workflow_id, continuation_id])
        DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=2)
        print(
            "RECOVERY="
            + canonical_json(
                {
                    "original_workflow_id": workflow_id,
                    "recovered_workflow_id": original_handle.get_workflow_id(),
                    "continuation_workflow_id": continuation_id,
                    "same_original_workflow": same_workflow,
                    "distinct_continuation_workflow": distinct_workflows,
                    "original_status": recovered_status,
                    "original_result": original_result,
                    "continuation_result": continuation_result,
                }
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=1)
        print(f"DBOS_CHILD_ERROR={type(exc).__name__}", flush=True)
        return 79


def run_durable_recovery(
    *,
    original_run_id: str,
    tool_call_id: str,
    policy_revision: str,
    original_history_json: str,
    continuation_history_json: str,
    wait_call_id: str,
) -> dict[str, Any]:
    base_command = [sys.executable, str(__file__), "--dbos-child"]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "PYTHONUTF8": "1",
        "CLOUDHELM_P0_ORIGINAL_RUN_ID": original_run_id,
        "CLOUDHELM_P0_TOOL_CALL_ID": tool_call_id,
        "CLOUDHELM_P0_POLICY_REVISION": policy_revision,
        "CLOUDHELM_P0_ORIGINAL_HISTORY_JSON": original_history_json,
        "CLOUDHELM_P0_CONTINUATION_HISTORY_JSON": continuation_history_json,
        "CLOUDHELM_P0_WAIT_CALL_ID": wait_call_id,
        "CLOUDHELM_P0_CRASH_AFTER_STEP": "1",
    }
    crashed = subprocess.run(
        [*base_command, "crash"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=45,
        env=environment,
        check=False,
    )
    match = re.search(r"^WORKFLOW_ID=([A-Za-z0-9_-]+)$", crashed.stdout, re.MULTILINE)
    require(match is not None, "DBOS crash child did not return a workflow identity")
    require(
        crashed.returncode == CRASH_EXIT_CODE,
        "DBOS child did not stop at the injected post-step checkpoint boundary",
    )
    workflow_id = match.group(1)
    environment["CLOUDHELM_P0_CRASH_AFTER_STEP"] = "0"
    recovered = subprocess.run(
        [*base_command, "recover", workflow_id],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=60,
        env=environment,
        check=False,
    )
    recovery_line = next(
        (
            line.removeprefix("RECOVERY=")
            for line in recovered.stdout.splitlines()
            if line.startswith("RECOVERY=")
        ),
        None,
    )
    require(
        recovered.returncode == 0 and recovery_line is not None,
        "DBOS recovery child failed; captured process details are suppressed",
    )
    return json.loads(recovery_line)


def run_probe(gateway: Gateway) -> dict[str, Any]:
    gate_revision = gateway.gate.revision
    before = gateway.evidence_snapshot(policy_revision=gate_revision)
    denied = []
    for key, supplied_revision in (
        ("sdk03/denied-stale-gate", "stale-policy"),
        ("sdk03/denied-revoked-tool", "p0-gate-r2"),
    ):
        if supplied_revision == "p0-gate-r2":
            gateway.gate.replace(revision=supplied_revision, allowed_tools={"query_counter"})
        try:
            gateway.submit_operation(
                idempotency_key=key,
                tool_call_id=f"call-denied-{len(denied) + 1}",
                args=OPERATION_ARGS,
                policy_revision=supplied_revision,
            )
            raise ProtocolProbeError("stale or revoked submit unexpectedly passed the Gateway")
        except GateDenied:
            denied.append(key)
    gateway.gate.replace(
        revision="p0-gate-r3",
        allowed_tools={
            "query_counter",
            "submit_operation",
            "complete_operation",
            "await_operation",
        },
    )
    gate_revision = gateway.gate.revision

    mixed_calls = [
        tool_call("query_counter", "call-mixed-query"),
        tool_call("submit_operation", "call-mixed-submit", OPERATION_ARGS),
        tool_call("await_operation", "call-mixed-await", {"operation_id": "unknown"}),
    ]
    mixed_rejection: list[str] = []

    async def reject_mixed_events(
        context: RunContext[Any], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        del context
        async for event in events:
            if isinstance(event, DeferredToolRequestsEvent):
                try:
                    classify_batch(event.requests.calls)
                except MixedBatchRejected:
                    mixed_rejection.append("rejected")

    mixed_agent = make_controlled_agent(mixed_calls)
    mixed_result = asyncio.run(
        run_streamed_agent(
            mixed_agent,
            "Request query, submit and wait together.",
            run_id="agent-run-sdk03-mixed",
            event_handler=reject_mixed_events,
        )
    )
    require(isinstance(mixed_result.output, DeferredToolRequests),
            "FunctionModel stream did not yield the mixed deferred batch")
    validate_history(mixed_result.all_messages())
    require(mixed_rejection == ["rejected"], "mixed batch was not rejected by the event adapter")
    mixed_after = gateway.evidence_snapshot(policy_revision=gate_revision)
    require(mixed_after["operations"] == before["operations"],
            "mixed batch started an Operation before its explicit rejection")

    query_calls = [
        tool_call("query_counter", "call-query-1"),
        tool_call("query_counter", "call-query-2"),
    ]
    query_callback_results: dict[str, Any] = {}

    async def query_events(
        context: RunContext[Any], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        del context
        async for event in events:
            if isinstance(event, DeferredToolRequestsEvent):
                require(classify_batch(event.requests.calls) == "query",
                        "query event batch was unexpectedly mixed")
                for call in event.requests.calls:
                    query_callback_results[call.tool_call_id] = gateway.query_counter(
                        policy_revision=gate_revision
                    )

    query_agent = make_controlled_agent(query_calls)
    query_run = asyncio.run(
        run_streamed_agent(
            query_agent,
            "Read the current probe counter twice.",
            run_id="agent-run-sdk03-query",
            event_handler=query_events,
        )
    )
    require(isinstance(query_run.output, DeferredToolRequests),
            "query stream did not end with deferred requests")
    query_requests = query_run.output
    require(set(query_callback_results) == {call.tool_call_id for call in query_calls},
            "query callbacks did not pass through Gateway")
    query_values = {
        call.tool_call_id: canonical_json(query_callback_results[call.tool_call_id])
        for call in query_calls
    }
    partial = query_requests.build_results(
        calls={query_calls[0].tool_call_id: query_values[query_calls[0].tool_call_id]}
    )
    remaining = query_requests.remaining(partial)
    require(
        remaining is not None
        and [call.tool_call_id for call in remaining.calls] == ["call-query-2"],
        "partial results did not leave the unresolved PydanticAI call pending",
    )
    resume_attempts = 0
    if query_requests.remaining(partial) is None:
        resume_attempts += 1
    require(resume_attempts == 0, "partial result batch was allowed to resume")
    query_results = complete_results(query_requests, query_values)
    query_resumed = asyncio.run(
        query_agent.run(
            None,
            message_history=query_run.all_messages(),
            deferred_tool_results=query_results,
            run_id="agent-run-sdk03-query-resumed",
        )
    )
    require(isinstance(query_resumed.output, str),
            "fully resolved query batch did not continue to a final response")
    validate_history(query_resumed.all_messages())

    submit_call = tool_call("submit_operation", "call-submit-original", OPERATION_ARGS)
    submit_events_seen: list[str] = []
    callback_results: list[tuple[dict[str, Any], bool]] = []

    async def submit_events(
        context: RunContext[Any], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        del context
        async for event in events:
            submit_events_seen.append(event.event_kind)
            if isinstance(event, DeferredToolRequestsEvent):
                require(classify_batch(event.requests.calls) == "submit",
                        "submit event batch was unexpectedly mixed")
                for call in event.requests.calls:
                    callback_results.append(
                        submit_callback(gateway, call, policy_revision=gate_revision)
                    )
                    callback_results.append(
                        submit_callback(gateway, call, policy_revision=gate_revision)
                    )

    submit_agent = make_controlled_agent([submit_call])
    submit_run = asyncio.run(
        run_streamed_agent(
            submit_agent,
            "Submit the fixed long operation.",
            run_id="agent-run-sdk04-submit",
            event_handler=submit_events,
        )
    )
    require(isinstance(submit_run.output, DeferredToolRequests),
            "stream callback run did not return deferred submit requests")
    submit_requests = submit_run.output
    require(submit_run.run_id == "agent-run-sdk04-submit",
            "PydanticAI changed the submit Run identity")
    require(
        callback_results
        and callback_results[0][1]
        and all(not created for _, created in callback_results[1:]),
        "duplicate streamed callback created another Operation",
    )
    receipt = callback_results[0][0]
    require(all(item[0] == receipt for item in callback_results),
            "callback replay changed the accepted receipt")
    replay_call = tool_call(
        "submit_operation",
        "call-submit-disconnect-replay",
        OPERATION_ARGS,
    )
    replay_receipt, replay_created = submit_callback(
        gateway, replay_call, policy_revision=gate_revision
    )
    require(not replay_created and replay_receipt == receipt,
            "disconnect replay with a changed tool-call ID started another Operation")

    accepted_results = complete_results(
        submit_requests,
        {submit_call.tool_call_id: canonical_json(receipt)},
    )
    submit_resumed = asyncio.run(
        submit_agent.run(
            None,
            message_history=submit_run.all_messages(),
            deferred_tool_results=accepted_results,
            run_id="agent-run-sdk04-submit-result",
        )
    )
    require(isinstance(submit_resumed.output, str),
            "accepted receipt did not resolve the deferred submit request")
    accepted_history = validate_history(submit_resumed.all_messages())
    accepted_json = ModelMessagesTypeAdapter.dump_json(accepted_history).decode("utf-8")

    operation_id = operation_identity(PROBE_ID, OPERATION_KEY)
    expected_digest = request_digest("submit_operation", OPERATION_ARGS)
    wait_call = tool_call(
        "await_operation",
        "call-await-original",
        {"operation_id": operation_id},
    )
    wait_callback_result: dict[str, Any] = {"value": "not-called"}
    wait_events_seen: list[str] = []

    async def wait_events(
        context: RunContext[Any], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        del context
        async for event in events:
            wait_events_seen.append(event.event_kind)
            if isinstance(event, DeferredToolRequestsEvent):
                require(classify_batch(event.requests.calls) == "wait",
                        "wait event batch was unexpectedly mixed")
                wait_callback_result["value"] = gateway.await_operation(
                    operation_id=operation_id,
                    expected_digest=expected_digest,
                    policy_revision=gate_revision,
                )

    wait_agent = make_controlled_agent([wait_call])
    wait_run = asyncio.run(
        run_streamed_agent(
            wait_agent,
            "Wait for the submitted operation result.",
            run_id="agent-run-sdk04-wait",
            event_handler=wait_events,
            message_history=accepted_history,
        )
    )
    require(isinstance(wait_run.output, DeferredToolRequests),
            "pending wait did not leave a PydanticAI deferred request")
    require(wait_callback_result["value"] is None,
            "unfinished Operation incorrectly returned a final result")
    wait_requests = wait_run.output
    empty_wait_results = wait_requests.build_results(calls={})
    require(wait_requests.remaining(empty_wait_results) is not None,
            "unfinished wait was incorrectly considered resolved")
    wait_history = validate_history(wait_run.all_messages())
    wait_history_json = ModelMessagesTypeAdapter.dump_json(wait_history).decode("utf-8")

    before_recovery = gateway.evidence_snapshot(policy_revision=gate_revision)
    recovery = run_durable_recovery(
        original_run_id=submit_run.run_id,
        tool_call_id=submit_call.tool_call_id,
        policy_revision=gate_revision,
        original_history_json=accepted_json,
        continuation_history_json=wait_history_json,
        wait_call_id=wait_call.tool_call_id,
    )
    require(recovery["same_original_workflow"], "DBOS recovery changed the original workflow ID")
    require(recovery["distinct_continuation_workflow"],
            "post-wait continuation reused the original DBOS workflow ID")
    original_result = recovery["original_result"]
    continuation_result = recovery["continuation_result"]
    require(original_result["agent_run_id"] == submit_run.run_id,
            "DBOS recovery changed the original AgentRun identity")
    require(continuation_result["agent_run_id"] == "agent-run-sdk04-after-wait",
            "wait continuation did not receive a new AgentRun identity")
    require(continuation_result["outcome"] == "result",
            "result completed before the continuation Run was not found")
    require(original_result["submit_created_operation"] is False,
            "DBOS step replay created a second Operation")
    require(original_result["effect_applied"] is True,
            "DBOS step did not apply its bounded Gateway side effect")

    final_result = continuation_result["final_result"]
    duplicate_final, duplicate_effect = gateway.complete_operation(
        operation_id=operation_id,
        expected_digest=expected_digest,
        result_id=RESULT_ID,
        result=RESULT_PAYLOAD,
        policy_revision=gate_revision,
    )
    require(duplicate_final == final_result, "duplicate result callback changed the final result")
    require(not duplicate_effect, "duplicate result callback applied the side effect twice")
    wait_results = complete_results(
        wait_requests,
        {wait_call.tool_call_id: canonical_json(duplicate_final)},
    )
    wait_resumed = asyncio.run(
        wait_agent.run(
            None,
            message_history=wait_history,
            deferred_tool_results=wait_results,
            run_id="agent-run-sdk04-after-wait",
        )
    )
    require(wait_resumed.run_id != wait_run.run_id,
            "waiting continuation did not use a new PydanticAI Run ID")
    final_history = validate_history(wait_resumed.all_messages())
    submit_return = next(
        part
        for message in final_history
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
        and part.tool_call_id == submit_call.tool_call_id
    )
    await_return = next(
        part
        for message in final_history
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
        and part.tool_call_id == wait_call.tool_call_id
    )
    require(json.loads(submit_return.content) == receipt,
            "final result overwrote the original submit accepted receipt")
    require(json.loads(await_return.content) == duplicate_final,
            "final result was not matched to the original await tool-call ID")

    after_recovery = gateway.evidence_snapshot(policy_revision=gate_revision)
    runtime_gate_delta = after_recovery["gate_checks"] - before_recovery["gate_checks"]
    require(runtime_gate_delta == 6,
            "DBOS restart replayed a completed Gateway step or missed a current gate check")
    require(after_recovery["operations"] == 1 and after_recovery["effects"] == 1,
            "Gateway evidence does not show exactly one Operation and one side effect")
    require(after_recovery["counter"] == 1, "bounded side-effect counter is not exactly one")

    return {
        "denied_current_gate_requests": denied,
        "mixed_batch": "explicitly rejected before dispatch",
        "mixed_batch_calls": [call.tool_name for call in mixed_result.output.calls],
        "query_calls": len(query_calls),
        "partial_batch_remaining": [call.tool_call_id for call in remaining.calls],
        "partial_batch_continuations": resume_attempts,
        "submit_event_kinds": submit_events_seen,
        "wait_event_kinds": wait_events_seen,
        "submit_tool_call_id": submit_call.tool_call_id,
        "operation_id": receipt["operation_id"],
        "request_digest": receipt["request_digest"],
        "submit_callback_created": callback_results[0][1],
        "duplicate_callback_created": callback_results[1][1],
        "disconnect_replay_created": replay_created,
        "wait_pending_returned_final": wait_callback_result["value"] is not None,
        "original_agent_run_id": original_result["agent_run_id"],
        "original_dbos_workflow_id": recovery["original_workflow_id"],
        "recovered_dbos_workflow_id": recovery["recovered_workflow_id"],
        "new_agent_run_id": continuation_result["agent_run_id"],
        "new_dbos_workflow_id": recovery["continuation_workflow_id"],
        "submit_receipt_preserved": True,
        "wait_result_completed": duplicate_final["status"] == "completed",
        "duplicate_result_effect_applied": duplicate_effect,
        "dbos_restart_gateway_check_delta": runtime_gate_delta,
        "snapshot": after_recovery,
        "query_resume_output": query_resumed.output,
        "submit_resume_output": submit_resumed.output,
        "wait_resume_output": wait_resumed.output,
        "accepted_history_bytes": len(accepted_json.encode("utf-8")),
        "wait_history_bytes": len(wait_history_json.encode("utf-8")),
        "pydantic_ai": version("pydantic-ai-slim"),
        "dbos": version("dbos"),
        "psycopg": version("psycopg"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbos-child", nargs="+", metavar="MODE")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dbos_child:
        stage = args.dbos_child[0]
        workflow_id = args.dbos_child[1] if len(args.dbos_child) > 1 else None
        return _dbos_child(stage, workflow_id)

    gate = CurrentGate()
    gateway = Gateway(PROBE_ID, gate)
    postgres_version = Gateway.prepare()
    gateway.reset_scope()
    try:
        evidence = run_probe(gateway)
    except (GatewayProbeError, ProtocolProbeError, AssertionError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"P0 protocol probe failed: {type(exc).__name__}: {exc}") from None
    print(
        canonical_json(
            {
                "status": "probe assertions passed; product capability remains unverified",
                "postgresql": postgres_version,
                "schema": "p0_protocol",
                "probe_id": PROBE_ID,
                "provider_requests": 0,
                "controlled_model": "PydanticAI FunctionModel stream_function",
                "evidence": evidence,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
