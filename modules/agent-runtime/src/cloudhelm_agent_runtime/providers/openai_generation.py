"""OpenAI 兼容 Provider 的 Responses/Chat 单次交换实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderResponseError,
    MissingProviderConfigurationError,
)
from cloudhelm_agent_runtime.providers.contracts import (
    ProviderConversation,
    normalize_response_item,
)
from cloudhelm_agent_runtime.providers.exchange import (
    PendingProviderTurn,
    ProviderExchangeResult,
)
from cloudhelm_agent_runtime.providers.prompt_cache import extract_call_metadata
from cloudhelm_agent_runtime.providers.request_payloads import (
    build_chat_completions_body,
    build_responses_body,
)
from cloudhelm_agent_runtime.providers.stream_events import (
    ChatCompletionsStreamAccumulator,
    ResponsesStreamAccumulator,
)
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.providers.usage import ProviderCallMetadata


class OpenAIGenerationContext(Protocol):
    """生成辅助所需的 Provider 最小配置与 SSE 边界。"""

    model_name: str | None
    reasoning_effort: str
    reasoning_summary: str | None
    reasoning_context: str | None
    max_output_tokens: int
    explicit_cache_breakpoint: bool

    def _post_sse(
        self,
        path: str,
        body: dict,
        handle_event,
        conversation: ProviderConversation | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ResponsesGeneration:
    """一次普通 Responses 生成的正文、usage 与回放 items。"""

    content: str
    metadata: ProviderCallMetadata | None
    response_items: list[dict]


def generate_responses(
    provider: OpenAIGenerationContext,
    agent_type: str,
    payload: BaseModel,
    output_model: type[BaseModel],
    conversation: ProviderConversation | None,
    current_input_items: list[dict],
) -> ResponsesGeneration:
    """调用 Responses API 并规范化完整有序 output items。"""

    model_name = _require_model(provider)
    body, prompt_cache_key = build_responses_body(
        agent_type=agent_type,
        payload=payload,
        output_model=output_model,
        model_name=model_name,
        current_input_items=current_input_items,
        conversation=conversation,
        reasoning_effort=provider.reasoning_effort,
        reasoning_summary=provider.reasoning_summary,
        reasoning_context=provider.reasoning_context,
        max_output_tokens=provider.max_output_tokens,
        explicit_cache_breakpoint=provider.explicit_cache_breakpoint,
    )
    accumulator = ResponsesStreamAccumulator()
    provider._post_sse(
        "/v1/responses",
        body,
        accumulator.handle,
        conversation,
    )
    metadata = (
        extract_call_metadata(
            accumulator.completed_response,
            prompt_cache_key,
        )
        if accumulator.completed_response is not None
        else None
    )
    try:
        response_items = [
            normalize_response_item(item)
            for item in accumulator.response_items
        ]
    except ValueError as exc:
        raise AgentProviderResponseError(
            f"responses API returned invalid output item: {exc}"
        ) from exc
    return ResponsesGeneration(
        content=accumulator.output_text(),
        metadata=metadata,
        response_items=response_items,
    )


def generate_chat_completions(
    provider: OpenAIGenerationContext,
    agent_type: str,
    output_model: type[BaseModel],
    conversation: ProviderConversation | None,
    current_input_items: list[dict],
) -> str:
    """调用兼容 Chat Completions 的 SSE 服务。"""

    body = build_chat_completions_body(
        agent_type=agent_type,
        output_model=output_model,
        model_name=_require_model(provider),
        conversation=conversation,
        current_input_items=current_input_items,
        reasoning_effort=provider.reasoning_effort,
        max_output_tokens=provider.max_output_tokens,
    )
    accumulator = ChatCompletionsStreamAccumulator()
    provider._post_sse(
        "/v1/chat/completions",
        body,
        accumulator.handle,
        conversation,
    )
    return accumulator.output_text()


def exchange_responses(
    provider: OpenAIGenerationContext,
    agent_type: str,
    payload: BaseModel,
    output_model: type[BaseModel],
    conversation: ProviderConversation,
    pending_turn: PendingProviderTurn,
    tools: tuple[ProviderToolDefinition, ...],
) -> ProviderExchangeResult:
    """执行允许工具-only 输出的一次 Responses 交换。"""

    body, prompt_cache_key = build_responses_body(
        agent_type=agent_type,
        payload=payload,
        output_model=output_model,
        model_name=_require_model(provider),
        current_input_items=pending_turn.request_items(),
        conversation=conversation,
        reasoning_effort=provider.reasoning_effort,
        reasoning_summary=provider.reasoning_summary,
        reasoning_context=provider.reasoning_context,
        max_output_tokens=provider.max_output_tokens,
        explicit_cache_breakpoint=provider.explicit_cache_breakpoint,
        tools=tools,
    )
    accumulator = ResponsesStreamAccumulator()
    provider._post_sse(
        "/v1/responses",
        body,
        accumulator.handle,
        conversation,
    )
    metadata = (
        extract_call_metadata(
            accumulator.completed_response,
            prompt_cache_key,
        )
        if accumulator.completed_response is not None
        else None
    )
    return ProviderExchangeResult.from_response(
        accumulator.response_items,
        output_text=accumulator.output_text_optional(),
        metadata=metadata,
        response_id=(
            metadata.response_id if metadata is not None else None
        ),
    )


def _require_model(provider: OpenAIGenerationContext) -> str:
    """读取已配置模型名。"""

    if provider.model_name is None:
        raise MissingProviderConfigurationError("model name is missing")
    return provider.model_name
