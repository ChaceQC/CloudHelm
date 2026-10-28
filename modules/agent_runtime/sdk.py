"""Ephemeral PydanticAI turn with admission at each actual HTTP attempt."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx
import rfc8785
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from modules.tool_gateway.gateway import GatewayFailure, ToolGateway

RequestAdmission = Callable[[str, int], Awaitable[str]]
MAX_REQUEST_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TurnResult:
    output: str
    new_messages: tuple[ModelMessage, ...]
    request_record_ids: tuple[str, ...]


class RuntimeFailure(Exception):
    def __init__(self, code: str, request_record_ids: tuple[str, ...] = ()):
        super().__init__(code)
        self.code = code
        self.request_record_ids = request_record_ids


class _RuntimeStop(Exception):
    pass


class _AdmittedTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        admit_request: RequestAdmission,
        max_requests: int,
        request_record_ids: list[str],
    ):
        self._inner = inner
        self._admit_request = admit_request
        self._max_requests = max_requests
        self._request_record_ids = request_record_ids

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if len(self._request_record_ids) >= self._max_requests:
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
        self._request_record_ids.append(record_id)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


async def run_turn(
    *,
    model_name: str,
    base_url: str,
    api_key: SecretStr,
    prompt: str,
    message_history: Sequence[ModelMessage],
    max_requests: int,
    max_seconds: float,
    max_output_tokens: int,
    admit_request: RequestAdmission,
    gateway: ToolGateway | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TurnResult:
    """Inputs and history live only in memory; persistence belongs to the caller."""
    request_record_ids: list[str] = []
    try:
        async with asyncio.timeout(max_seconds):
            admitted = _AdmittedTransport(
                transport or httpx.AsyncHTTPTransport(), admit_request, max_requests, request_record_ids
            )
            async with httpx.AsyncClient(transport=admitted, follow_redirects=False) as http_client:
                client = AsyncOpenAI(
                    api_key=api_key.get_secret_value(),
                    base_url=base_url,
                    http_client=http_client,
                    max_retries=2,
                    timeout=None,
                )
                model = OpenAIResponsesModel(model_name, provider=OpenAIProvider(openai_client=client))
                agent = Agent(model, tools=gateway.tools() if gateway else ())
                result = await agent.run(
                    prompt,
                    message_history=message_history,
                    model_settings={"max_tokens": max_output_tokens, "parallel_tool_calls": False,
                                    "openai_store": False, "openai_service_tier": "default"},
                    usage_limits=UsageLimits(request_limit=max_requests, output_tokens_limit=max_output_tokens),
                )
                return TurnResult(result.output, tuple(result.new_messages()), tuple(request_record_ids))
    except TimeoutError:
        code = "turn_timeout"
    except (_RuntimeStop, GatewayFailure) as error:
        code = str(error)
    except UsageLimitExceeded:
        code = "turn_limit_reached"
    except Exception:
        code = "model_request_failed"
    # Raise outside the handler so provider, callback, and history exceptions are not chained.
    raise RuntimeFailure(code, tuple(request_record_ids))
