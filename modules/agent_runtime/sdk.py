"""Ephemeral PydanticAI turn with admission at each actual HTTP attempt."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import rfc8785
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from modules.tool_gateway.gateway import GatewayFailure, ToolGateway

RequestAdmission = Callable[[str, int], Awaitable[str]]
ResponseRecorder = Callable[[str, dict[str, Any]], Awaitable[None]]
MAX_REQUEST_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TurnOutput:
    messages: tuple[ModelMessage, ...]
    deferred: DeferredToolRequests | None


class RuntimeFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _RuntimeStop(Exception):
    pass


class _AdmittedTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        admit_request: RequestAdmission,
        record_response: ResponseRecorder,
        max_requests: int,
    ):
        self._inner = inner
        self._admit_request = admit_request
        self._record_response = record_response
        self._max_requests = max_requests
        self._request_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._request_count >= self._max_requests:
            raise _RuntimeStop("request_limit_reached")
        raw = await request.aread()
        if len(raw) > MAX_REQUEST_BYTES:
            raise _RuntimeStop("request_body_too_large")
        if request.method != "POST":
            raise _RuntimeStop("unsupported_model_request")
        body = json.loads(raw)
        if body.get("stream") or any(tool.get("type") != "function" for tool in body.get("tools", [])):
            raise _RuntimeStop("unsupported_model_request")
        digest = "sha256:" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()
        try:
            record_id = await self._admit_request(digest, len(raw))
        except Exception:
            raise _RuntimeStop("request_admission_denied") from None
        self._request_count += 1
        response = await self._inner.handle_async_request(request)
        try:
            await response.aread()
        except BaseException:
            await response.aclose()
            raise

        data: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except (ValueError, UnicodeDecodeError):
            pass
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        input_details = usage.get("input_tokens_details")
        input_details = input_details if isinstance(input_details, dict) else {}
        payload = {
            "provider_response_id": data.get("id"),
            "provider_request_id": response.headers.get("x-request-id"),
            "response_model": data.get("model"),
            "service_tier": data.get("service_tier"),
            "usage": {
                "input_tokens": usage.get("input_tokens"),
                "cached_input_tokens": input_details.get("cached_tokens"),
                "cache_write_tokens": input_details.get("cache_write_tokens"),
                "output_tokens": usage.get("output_tokens"),
            },
        }
        try:
            await self._record_response(record_id, payload)
        except Exception:
            raise _RuntimeStop("response_record_failed") from None
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


async def run_turn(
    *,
    model_name: str,
    base_url: str,
    api_key: SecretStr,
    prompt: str | None,
    message_history: Sequence[ModelMessage],
    max_requests: int,
    max_seconds: float,
    max_output_tokens: int,
    admit_request: RequestAdmission,
    record_response: ResponseRecorder,
    deferred_results: DeferredToolResults | None = None,
    gateway: ToolGateway | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    instructions: str | None = None,
) -> TurnOutput:
    """Inputs and history live only in memory; persistence belongs to the caller."""
    try:
        returned_ids: set[str] = set()
        pending_ids: set[str] = set()
        for message in reversed(message_history):
            if isinstance(message, ModelResponse):
                calls = message.tool_calls
                call_ids = {call.tool_call_id for call in calls}
                if len(call_ids) != len(calls):
                    raise _RuntimeStop("deferred_results_incomplete")
                pending_ids = call_ids - returned_ids
                break
            if isinstance(message, ModelRequest):
                returned_ids.update(part.tool_call_id for part in message.parts
                    if isinstance(part, (ToolReturnPart, RetryPromptPart)) and part.tool_call_id)
        if deferred_results is not None:
            result_ids = set(deferred_results.calls) | set(deferred_results.approvals)
            if (not pending_ids or pending_ids != result_ids
                    or set(deferred_results.calls) & set(deferred_results.approvals)):
                raise _RuntimeStop("deferred_results_incomplete")
        elif pending_ids:
            raise _RuntimeStop("deferred_results_required")
        async with asyncio.timeout(max_seconds):
            admitted = _AdmittedTransport(transport or httpx.AsyncHTTPTransport(), admit_request,
                                           record_response, max_requests)
            async with httpx.AsyncClient(transport=admitted, follow_redirects=False) as http_client:
                client = AsyncOpenAI(
                    api_key=api_key.get_secret_value(),
                    base_url=base_url,
                    http_client=http_client,
                    max_retries=2,
                    timeout=None,
                )
                model = OpenAIResponsesModel(model_name, provider=OpenAIProvider(openai_client=client))
                agent = Agent(model, tools=gateway.tools() if gateway else (), instructions=instructions,
                              output_type=[str, DeferredToolRequests])
                result = await agent.run(
                    None if deferred_results is not None else prompt,
                    message_history=message_history,
                    deferred_tool_results=deferred_results,
                    model_settings={"max_tokens": max_output_tokens, "parallel_tool_calls": False,
                                    "openai_store": False, "openai_service_tier": "default"},
                    usage_limits=UsageLimits(request_limit=max_requests, output_tokens_limit=max_output_tokens),
                )
                return TurnOutput(tuple(result.new_messages()),
                                  result.output if isinstance(result.output, DeferredToolRequests) else None)
    except TimeoutError:
        code = "turn_timeout"
    except (_RuntimeStop, GatewayFailure) as error:
        code = str(error)
    except UsageLimitExceeded:
        code = "turn_limit_reached"
    except Exception:
        code = "model_request_failed"
    # Raise outside the handler so provider, callback, and history exceptions are not chained.
    raise RuntimeFailure(code)
