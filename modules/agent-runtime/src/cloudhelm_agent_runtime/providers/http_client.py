"""OpenAI-compatible HTTP SSE 请求、headers 与端点解析。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib import error, request

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
)
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.http_streaming import (
    iter_sse_data,
    parse_retry_after_seconds,
)

DEFAULT_CODEX_USER_AGENT = "codex_cli_rs/0.0.0 (CloudHelm)"
DEFAULT_CODEX_ORIGINATOR = "codex_cli_rs"


def post_sse(
    *,
    endpoint: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
    handle_event: Callable[[dict[str, Any]], None],
    urlopen: Callable[..., Any],
) -> None:
    """发送一个 HTTP SSE 请求并把 data JSON 逐项交给累积器。"""

    http_request = request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=timeout_seconds) as response:
            for raw_data in iter_sse_data(response):
                if raw_data == "[DONE]":
                    break
                try:
                    event_payload = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    raise AgentProviderResponseError(
                        "model API stream returned invalid JSON event"
                    ) from exc
                if not isinstance(event_payload, dict):
                    raise AgentProviderResponseError(
                        "model API stream event must be a JSON object"
                    )
                handle_event(event_payload)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        retryable = exc.code in {408, 409, 429} or exc.code >= 500
        raise AgentProviderRequestError(
            f"model API returned HTTP {exc.code}: {detail}",
            retryable=retryable,
            retry_after_seconds=parse_retry_after_seconds(exc.headers, detail),
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise AgentProviderRequestError(
            f"model API request failed: {type(exc).__name__}"
        ) from exc


def build_request_headers(
    *,
    api_key: str | None,
    user_agent: str,
    originator: str,
    conversation: ProviderConversation | None,
) -> dict[str, str]:
    """构造 Codex 风格请求 headers，不包含 prompt 正文。"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": validate_header_value(user_agent, "user_agent"),
        "originator": validate_header_value(originator, "originator"),
    }
    if conversation is None:
        return headers
    conversation_id = validate_header_value(
        conversation.conversation_id,
        "conversation_id",
    )
    headers["x-client-request-id"] = conversation_id
    headers["session-id"] = conversation_id
    headers["thread-id"] = conversation_id
    if conversation.parent_conversation_id:
        headers["x-codex-parent-thread-id"] = validate_header_value(
            conversation.parent_conversation_id,
            "parent_conversation_id",
        )
    if conversation.source_type == "subagent" and conversation.agent_role:
        headers["x-openai-subagent"] = validate_header_value(
            conversation.agent_role,
            "agent_role",
        )
    return headers


def resolve_endpoint(api_base: str | None, path: str) -> str:
    """兼容 API base 以主机或 `/v1` 结尾的配置。"""

    if api_base is None:
        raise MissingProviderConfigurationError("model API base is missing")
    if api_base.endswith("/v1") and path.startswith("/v1/"):
        return f"{api_base}{path[3:]}"
    return f"{api_base}{path}"


def validate_header_value(value: str, field_name: str) -> str:
    """校验单行非空 header 值并返回原值。"""

    if not value.strip() or "\r" in value or "\n" in value:
        raise ValueError(f"{field_name} must be a non-empty single-line value")
    return value
