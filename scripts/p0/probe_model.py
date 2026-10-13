from __future__ import annotations

import argparse
import asyncio
import gzip
import importlib.metadata
import json
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.durable_exec.dbos import DBOSDurability
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from model_boundary import (
    AdmissionTransport,
    AdmissionDenied,
    BASE_URL,
    FAULT_BATCH_KEY,
    FAULT_UNKNOWN_BATCH_KEY,
    FIXED_BATCH_REQUEST_CAP,
    JOURNAL_PATH,
    LIVE_CANDIDATE_REVISION,
    LIVE_BATCH_KEY,
    MODEL_NAME,
    PREVIOUS_REAL_HTTP_COUNT,
    PROBE_OUTPUT_CAP,
    REASONING_EFFORT,
    RequestBudget,
    RequestJournal,
    STREAM_BATCH_KEY,
    STREAM_CANDIDATE_REVISION,
    STREAM_EVENT_LIMIT,
    STREAM_EVENT_TYPE_LIMIT,
    STREAM_REQUEST_CAP,
    TASK_CUMULATIVE_HTTP_CAP,
    WIRE_API,
    _extract_vendor_usage,
    _authorized_config,
    safe_record,
    safe_status,
)

MODEL_SETTINGS = {
    "max_tokens": PROBE_OUTPUT_CAP,
    "openai_reasoning_effort": REASONING_EFFORT,
}


class ShortAnswer(BaseModel):
    answer: str


class RepairAnswer(BaseModel):
    accepted: bool
    reason: str


class CompactSummary(BaseModel):
    summary: str


def _print_records(transport: AdmissionTransport, scenario: str) -> None:
    for record in transport.budget.records:
        if record.scenario == scenario:
            print(json.dumps(safe_record(record), ensure_ascii=False, separators=(",", ":")))


def _attach_sdk_usage(result: Any, transport: AdmissionTransport, scenario: str) -> None:
    responses = [
        message
        for message in result.new_messages()
        if isinstance(message, ModelResponse)
    ]
    records = [
        record
        for record in transport.budget.records
        if record.scenario == scenario and record.http_status == 200
    ]
    for message, record in zip(responses, records):
        if record.vendor_usage is None:
            input_tokens = getattr(message.usage, "input_tokens", None)
            output_tokens = getattr(message.usage, "output_tokens", None)
            if isinstance(input_tokens, int) and input_tokens > 0:
                record.vendor_usage = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
                    "total_tokens": None,
                    "cached_input_tokens": None,
                }
                record.usage_source = "PydanticAI ModelResponse.usage"
        record.provider_response_id = message.provider_response_id
        if record.provider_response_id or record.provider_request_id:
            record.journal_outcome = "provider_metadata_observed"
            transport.budget.journal.append_result(record, "provider_metadata_observed")


def _print_fault_result(
    transport: AdmissionTransport,
    handler_calls: int,
    error: BaseException | None,
    usage_parser_ok: bool,
    journal: RequestJournal,
    had_existing_records: bool,
) -> bool:
    reopened = RequestJournal(JOURNAL_PATH, FAULT_BATCH_KEY, 2, 128)
    saved_records = reopened.records()
    current_records = transport.budget.records
    if had_existing_records:
        passed = (
            handler_calls == 0
            and not current_records
            and isinstance(error, AdmissionDenied)
            and len(saved_records) == 2
        )
        mode = "restart_replay_blocked"
    else:
        passed = (
            handler_calls == 2
            and len(current_records) == 2
            and all(record.http_status == 503 for record in current_records)
            and all(record.reserved_output_tokens == record.max_output_tokens for record in current_records)
            and len(saved_records) == 2
            and [r.request_record_id for r in current_records]
            == [r.request_record_id for r in saved_records]
        )
        mode = "first_write_and_reopen"
    passed = passed and journal.batch_id == reopened.batch_id and usage_parser_ok
    print(
        "fault_check="
        + ("passed" if passed else "failed")
        + f" mode={mode} batch_id={reopened.batch_id}"
        + f" simulated_http={handler_calls} vendor_http=0 sdk_max_retries=1"
        + f" usage_parser_fixtures={'passed' if usage_parser_ok else 'failed'}"
        + f" persisted_records={len(saved_records)}"
    )
    if error is not None:
        print(f"fault_error_type={type(error).__name__} status={safe_status(error)}")
    for record in saved_records:
        print(json.dumps(safe_record(record), ensure_ascii=False, separators=(",", ":")))
    return passed


async def run_fault_check() -> bool:
    """Inject two local 503s to observe the OpenAI SDK retry boundary."""
    handler_calls = 0

    async def fail_for_each_sdk_attempt(request: httpx.Request) -> httpx.Response:
        nonlocal handler_calls
        handler_calls += 1
        return httpx.Response(503, json={"error": {"type": "injected"}}, request=request)

    journal = RequestJournal(JOURNAL_PATH, FAULT_BATCH_KEY, 2, 128)
    existing_records = journal.records()
    budget = RequestBudget(journal)
    inner = httpx.MockTransport(fail_for_each_sdk_attempt)
    transport = AdmissionTransport(inner, budget, live=False)
    http_client = httpx.AsyncClient(transport=transport, timeout=10.0)
    caught: BaseException | None = None
    try:
        async with AsyncOpenAI(
            api_key="fault-injection-only",
            base_url=BASE_URL,
            http_client=http_client,
            max_retries=1,
        ) as client:
            model = OpenAIResponsesModel(
                MODEL_NAME,
                provider=OpenAIProvider(openai_client=client),
            )
            agent = Agent(
                model,
                model_settings={"max_tokens": 64, "openai_reasoning_effort": REASONING_EFFORT},
                retries=0,
            )
            with transport.scenario("fault_injected_sdk_retry", max_logical_calls=2):
                try:
                    await agent.run("Reply with one short word.")
                except Exception as exc:
                    caught = exc
    except Exception as exc:
        caught = exc
    expected_usage = {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
        "cached_input_tokens": 2,
    }
    json_fixture = (
        b'{"usage":{"input_tokens":7,"output_tokens":3,"total_tokens":10,'
        b'"input_tokens_details":{"cached_tokens":2}}}'
    )
    sse_fixture = (
        b'data: {"type":"response.completed","response":{"usage":'
        b'{"input_tokens":7,"output_tokens":3,"total_tokens":10,'
        b'"input_tokens_details":{"cached_tokens":2}}}}\n\n'
    )
    json_usage, _ = _extract_vendor_usage(gzip.compress(json_fixture), "gzip")
    sse_usage, _ = _extract_vendor_usage(sse_fixture, None)
    usage_parser_ok = json_usage == expected_usage and sse_usage == expected_usage
    retry_ok = _print_fault_result(
        transport,
        handler_calls,
        caught,
        usage_parser_ok,
        journal,
        bool(existing_records),
    )
    unknown_ok = await run_unknown_journal_check()
    return retry_ok and unknown_ok


async def run_unknown_journal_check() -> bool:
    """Persist an outcome-unknown transport loss and prove restart blocks replay."""
    calls = 0
    journal = RequestJournal(JOURNAL_PATH, FAULT_UNKNOWN_BATCH_KEY, 1, 64)
    had_existing = bool(journal.records())
    budget = RequestBudget(journal)

    async def lose_response(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadError("injected response loss")

    transport = AdmissionTransport(httpx.MockTransport(lose_response), budget, live=False)
    http_client = httpx.AsyncClient(transport=transport, timeout=10.0)
    error: BaseException | None = None
    try:
        async with AsyncOpenAI(
            api_key="fault-injection-only",
            base_url=BASE_URL,
            http_client=http_client,
            max_retries=0,
        ) as client:
            agent = Agent(
                OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client)),
                model_settings={"max_tokens": 64, "openai_reasoning_effort": REASONING_EFFORT},
                retries=0,
            )
            with transport.scenario("fault_unknown_response", max_logical_calls=1):
                try:
                    await agent.run("Reply with one short word.")
                except Exception as exc:
                    error = exc
    except Exception as exc:
        error = exc

    reopened = RequestJournal(JOURNAL_PATH, FAULT_UNKNOWN_BATCH_KEY, 1, 64)
    saved = reopened.records()
    if had_existing:
        passed = (
            calls == 0
            and not budget.records
            and isinstance(error, AdmissionDenied)
            and len(saved) == 1
            and saved[0].journal_outcome == "unknown"
        )
        mode = "restart_replay_blocked"
    else:
        passed = (
            calls == 1
            and len(budget.records) == 1
            and len(saved) == 1
            and saved[0].journal_outcome == "unknown"
            and saved[0].transport_error_type == "ReadError"
        )
        mode = "response_loss_recorded_unknown"
    passed = passed and journal.batch_id == reopened.batch_id
    print(
        f"unknown_journal_check={'passed' if passed else 'failed'} mode={mode} "
        f"batch_id={reopened.batch_id} simulated_http={calls} vendor_http=0 "
        f"persisted_records={len(saved)}"
    )
    for record in saved:
        print(json.dumps(safe_record(record), ensure_ascii=False, separators=(",", ":")))
    return passed


async def _run_case(
    agent: Agent[Any, Any],
    transport: AdmissionTransport,
    scenario: str,
    prompt: str,
    *,
    max_calls: int = 1,
    message_history: list[Any] | None = None,
) -> Any:
    with transport.scenario(scenario, max_logical_calls=max_calls):
        result = await agent.run(prompt, message_history=message_history)
    _attach_sdk_usage(result, transport, scenario)
    _print_records(transport, scenario)
    return result


async def run_live_batch() -> bool:
    """Run only the fixed, explicitly authorized, bounded provider batch."""
    journal = RequestJournal(
        JOURNAL_PATH,
        LIVE_BATCH_KEY,
        FIXED_BATCH_REQUEST_CAP,
        FIXED_BATCH_REQUEST_CAP * PROBE_OUTPUT_CAP,
    )
    saved_records = journal.records()
    if saved_records:
        print(
            f"live_batch=blocked candidate_revision={LIVE_CANDIDATE_REVISION} "
            f"replay=existing_records batch_id={journal.batch_id} "
            f"persisted_records={len(saved_records)} real_http_requests=0"
        )
        for record in saved_records:
            print(json.dumps(safe_record(record), ensure_ascii=False, separators=(",", ":")))
        return False
    config = _authorized_config()
    budget = RequestBudget(journal)
    inner = httpx.AsyncHTTPTransport(retries=0)
    transport = AdmissionTransport(inner, budget, live=True, expected_config=config)
    http_client = httpx.AsyncClient(transport=transport, timeout=45.0)
    success = True

    try:
        async with AsyncOpenAI(
            api_key=config.credential,
            base_url=config.base_url,
            http_client=http_client,
            max_retries=1,
        ) as client:
            provider = OpenAIProvider(openai_client=client)
            model = OpenAIResponsesModel(MODEL_NAME, provider=provider)

            normal_agent = Agent(
                model,
                output_type=ShortAnswer,
                model_settings=MODEL_SETTINGS,
                retries=1,
            )
            await _run_case(
                normal_agent,
                transport,
                "normal_structured_response",
                "Return one short answer: what does a readiness check confirm?",
            )

            repair_agent = Agent(
                model,
                output_type=RepairAnswer,
                model_settings=MODEL_SETTINGS,
                retries=1,
            )
            rejected = {"first": True}

            @repair_agent.output_validator
            def inject_one_validation_rejection(ctx: Any, output: RepairAnswer) -> RepairAnswer:
                del ctx
                if rejected["first"]:
                    rejected["first"] = False
                    raise ModelRetry("Local probe validator deliberately rejects the first result.")
                return output

            await _run_case(
                repair_agent,
                transport,
                "validator_repair",
                "Return accepted=true and a very short reason for this fixed probe.",
                max_calls=2,
            )

            summary_agent = Agent(
                model,
                output_type=CompactSummary,
                model_settings=MODEL_SETTINGS,
                retries=1,
            )
            summary_result = await _run_case(
                summary_agent,
                transport,
                "context_compaction_summary",
                "Summarize in one sentence: A deployment is ready only after the artifact, configuration, approval, and current target checks are recorded.",
            )
            compacted_text = summary_result.output.summary[:240]

            continuation_agent = Agent(
                model,
                output_type=ShortAnswer,
                model_settings=MODEL_SETTINGS,
                retries=1,
            )
            continued = await _run_case(
                continuation_agent,
                transport,
                "post_compaction_new_epoch",
                f"Continue from this compacted summary and name the next safe check: {compacted_text}",
            )

            recovered_history = continued.all_messages()
            recovered_agent = Agent(
                model,
                output_type=ShortAnswer,
                model_settings=MODEL_SETTINGS,
                retries=1,
            )
            await _run_case(
                recovered_agent,
                transport,
                "restored_history_new_request",
                "Continue from the restored committed history with one short next step.",
                message_history=recovered_history,
            )
            del summary_result, continued, recovered_history
    except Exception as exc:
        success = False
        print(f"live_error_type={type(exc).__name__} status={safe_status(exc)}")
        if transport.budget.records:
            _print_records(transport, transport.budget.records[-1].scenario)

    usage_records = [record for record in budget.records if record.vendor_usage is not None]
    expected_scenarios = {
        "normal_structured_response": 1,
        "validator_repair": 2,
        "context_compaction_summary": 1,
        "post_compaction_new_epoch": 1,
        "restored_history_new_request": 1,
    }
    actual_scenarios = {
        scenario: sum(record.scenario == scenario for record in budget.records)
        for scenario in expected_scenarios
    }
    preflight_visible = all(record.preflight_commit_visible for record in budget.records)
    batch_passed = (
        success
        and actual_scenarios == expected_scenarios
        and len(budget.records) == FIXED_BATCH_REQUEST_CAP
        and len(usage_records) == FIXED_BATCH_REQUEST_CAP
        and preflight_visible
    )
    print(
        f"live_batch={'passed' if batch_passed else 'blocked'} "
        f"candidate_revision={LIVE_CANDIDATE_REVISION} "
        f"real_http_requests={len(budget.records)} "
        f"vendor_usage_responses={len(usage_records)} "
        f"reserved_output_tokens={budget.reserved_output_tokens} "
        f"preflight_commit_visible={preflight_visible} "
        f"batch_id={budget.batch_id} "
        "monetary_cost=unknown"
    )
    return batch_passed


async def run_live_stream_probe() -> bool:
    """Run one Responses SSE request and keep only bounded event names and counts."""
    journal = RequestJournal(
        JOURNAL_PATH,
        STREAM_BATCH_KEY,
        STREAM_REQUEST_CAP,
        PROBE_OUTPUT_CAP,
    )
    saved_records = journal.records()
    if saved_records:
        print(
            f"stream_probe=blocked candidate_revision={STREAM_CANDIDATE_REVISION} "
            f"replay=existing_records batch_id={journal.batch_id} "
            f"persisted_records={len(saved_records)} real_http_requests=0"
        )
        for record in saved_records:
            print(json.dumps(safe_record(record), ensure_ascii=False, separators=(",", ":")))
        return False

    config = _authorized_config()
    budget = RequestBudget(journal)
    transport = AdmissionTransport(
        httpx.AsyncHTTPTransport(retries=0),
        budget,
        live=True,
        expected_config=config,
    )
    http_client = httpx.AsyncClient(transport=transport, timeout=45.0)
    scenario = "responses_stream_events"
    agent_event_counts: dict[str, int] = {}
    event_count_truncated = False
    final_result: Any | None = None
    stream_error: BaseException | None = None

    try:
        async with AsyncOpenAI(
            api_key=config.credential,
            base_url=config.base_url,
            http_client=http_client,
            max_retries=0,
        ) as client:
            agent = Agent(
                OpenAIResponsesModel(
                    MODEL_NAME,
                    provider=OpenAIProvider(openai_client=client),
                ),
                model_settings=MODEL_SETTINGS,
                retries=0,
            )
            with transport.scenario(
                scenario,
                max_logical_calls=1,
                require_stream=True,
            ):
                async with agent.run_stream_events(
                    "Reply with one short sentence confirming this is a streaming transport probe."
                ) as events:
                    async for event in events:
                        event_type = type(event).__name__
                        if sum(agent_event_counts.values()) >= STREAM_EVENT_LIMIT:
                            event_count_truncated = True
                            continue
                        if (
                            event_type not in agent_event_counts
                            and len(agent_event_counts) >= STREAM_EVENT_TYPE_LIMIT
                        ):
                            event_type = "__other__"
                        agent_event_counts[event_type] = agent_event_counts.get(event_type, 0) + 1
                    final_result = events.result
    except Exception as exc:
        stream_error = exc

    record = budget.records[0] if budget.records else None
    if record is not None:
        if final_result is not None:
            _attach_sdk_usage(final_result, transport, scenario)
            shape = record.response_shape or {}
            shape["pydantic_agent_event_type_counts"] = agent_event_counts
            shape["pydantic_agent_event_count_truncated"] = event_count_truncated
            record.response_shape = shape
            record.journal_outcome = "stream_final_result_observed"
            journal.append_result(record, "stream_final_result_observed")
        elif record.journal_outcome != "unknown":
            record.transport_error_type = (
                type(stream_error).__name__ if stream_error is not None else "MissingFinalStreamResult"
            )
            record.journal_outcome = "unknown"
            journal.append_result(record, "unknown")

    if stream_error is not None:
        print(f"stream_error_type={type(stream_error).__name__} status={safe_status(stream_error)}")

    raw_event_counts = (
        (record.response_shape or {}).get("event_type_counts", {}) if record is not None else {}
    )
    response_content_type = record.response_content_type if record is not None else None
    sse_content_type = bool(
        response_content_type
        and response_content_type.lower().startswith("text/event-stream")
    )
    completed_sse = bool(raw_event_counts.get("response.completed"))
    passed = bool(
        stream_error is None
        and final_result is not None
        and record is not None
        and record.stream_requested
        and record.preflight_commit_visible
        and record.http_status == 200
        and sse_content_type
        and completed_sse
        and record.vendor_usage is not None
        and record.provider_response_id is not None
    )
    if record is not None:
        print(
            f"stream_probe={'passed' if passed else 'blocked'} "
            f"candidate_revision={STREAM_CANDIDATE_REVISION} "
            f"request_record_id={record.request_record_id} "
            f"stream_body={record.stream_requested} http_status={record.http_status} "
            f"content_type={response_content_type} "
            f"sse_event_counts={json.dumps(raw_event_counts, sort_keys=True)} "
            f"pydantic_event_counts={json.dumps(agent_event_counts, sort_keys=True)} "
            f"usage={json.dumps(record.vendor_usage, sort_keys=True)} "
            f"provider_response_id={record.provider_response_id} "
            f"x_request_id={record.provider_request_id} "
            f"preflight_commit_visible={record.preflight_commit_visible} "
            f"batch_id={record.batch_id} monetary_cost=unknown"
        )
        _print_records(transport, scenario)
    else:
        print(
            f"stream_probe=blocked candidate_revision={STREAM_CANDIDATE_REVISION} "
            "real_http_requests=0 monetary_cost=unknown"
        )
    return passed


def print_diagnostic() -> None:
    versions = {}
    for package in ("pydantic-ai-slim", "openai", "httpx", "dbos"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    print("mode=diagnostic live=disabled real_http_requests=0")
    print(f"model={MODEL_NAME} reasoning={REASONING_EFFORT} wire_api={WIRE_API}")
    print(
        f"previous_session_real_http={PREVIOUS_REAL_HTTP_COUNT} "
        f"stream_candidate={STREAM_CANDIDATE_REVISION} "
        f"stream_request_cap={STREAM_REQUEST_CAP} "
        f"task_cumulative_probe_cap={TASK_CUMULATIVE_HTTP_CAP} "
        f"max_output_tokens_per_request={PROBE_OUTPUT_CAP}"
    )
    print(f"versions={json.dumps(versions, sort_keys=True)}")
    print(f"responses_model={OpenAIResponsesModel.__module__}.{OpenAIResponsesModel.__name__}")
    print(f"dbos_durability={DBOSDurability.__module__}.{DBOSDurability.__name__}")
    print("currency_budget=unknown; live provider credentials are not read in diagnostic mode")
    print("commands=uv run python scripts/p0/probe_model.py --fault-check | --live | --live-stream")


async def _async_main(args: argparse.Namespace) -> int:
    if args.fault_check and not await run_fault_check():
        return 1
    if args.live_stream:
        return 0 if await run_live_stream_probe() else 1
    if args.live:
        return 0 if await run_live_batch() else 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded PydanticAI Responses boundary probe")
    parser.add_argument("--fault-check", action="store_true", help="inject local HTTP 503s; no vendor calls")
    parser.add_argument("--live", action="store_true", help="run the explicitly authorized fixed provider batch")
    parser.add_argument(
        "--live-stream",
        action="store_true",
        help="run one explicitly authorized Responses SSE request",
    )
    args = parser.parse_args()
    if args.live_stream and (args.live or args.fault_check):
        parser.error("--live-stream cannot be combined with --live or --fault-check")
    if not args.fault_check and not args.live and not args.live_stream:
        print_diagnostic()
        return 0
    try:
        return asyncio.run(_async_main(args))
    except Exception as exc:
        print(f"probe_error_type={type(exc).__name__} status={safe_status(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
