"""OpenAI 兼容 structured outputs provider。

默认使用 HTTP SSE Responses API。普通 Agent 角色切换复用调用方传入的同一
ProviderConversation；只有显式 subagent conversation 才会发送新的 thread id
以及 parent/subagent headers。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar
from urllib import request

from pydantic import BaseModel

from cloudhelm_agent_runtime.instructions import build_turn_input_items
from cloudhelm_agent_runtime.providers.base import (
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
    StructuredAgentProvider,
    ToolCapableStructuredAgentProvider,
)
from cloudhelm_agent_runtime.providers.contracts import (
    ProviderConversation,
    assistant_message_item,
)
from cloudhelm_agent_runtime.providers.http_client import (
    DEFAULT_CODEX_ORIGINATOR,
    DEFAULT_CODEX_USER_AGENT,
    build_request_headers,
    post_sse,
    resolve_endpoint,
    validate_header_value,
)
from cloudhelm_agent_runtime.providers.exchange import (
    PendingProviderTurn,
    ProviderExchangeResult,
)
from cloudhelm_agent_runtime.providers.openai_generation import (
    exchange_responses,
    generate_chat_completions,
    generate_responses,
)
from cloudhelm_agent_runtime.providers.openai_provider_support import (
    parse_structured_output,
    run_with_retries,
)
from cloudhelm_agent_runtime.providers.prompt_cache import (
    combine_call_metadata,
)
from cloudhelm_agent_runtime.providers.request_payloads import (
    ApiMode,
    ReasoningContext,
    ReasoningEffort,
    ReasoningSummary,
)
from cloudhelm_agent_runtime.providers.usage import ProviderCallMetadata
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition

T = TypeVar("T")


class OpenAICompatibleProvider(ToolCapableStructuredAgentProvider):
    """OpenAI 兼容模型 provider。"""

    name = "openai_compatible"

    def __init__(
        self,
        api_base: str | None,
        api_key: str | None,
        model_name: str | None,
        *,
        api_mode: ApiMode = "responses",
        reasoning_effort: ReasoningEffort = "xhigh",
        reasoning_summary: ReasoningSummary | None = "auto",
        reasoning_context: ReasoningContext | None = "all_turns",
        max_output_tokens: int = 32768,
        timeout_seconds: int = 120,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        explicit_cache_breakpoint: bool = False,
        user_agent: str = DEFAULT_CODEX_USER_AGENT,
        originator: str = DEFAULT_CODEX_ORIGINATOR,
    ) -> None:
        """初始化 Provider，并拒绝可造成 header 注入的配置。"""

        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        validate_header_value(user_agent, "user_agent")
        validate_header_value(originator, "originator")
        self.api_base = api_base.rstrip("/") if api_base else None
        self.api_key = api_key
        self.model_name = model_name
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort
        self.reasoning_summary = reasoning_summary
        self.reasoning_context = reasoning_context
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.explicit_cache_breakpoint = explicit_cache_breakpoint
        self.user_agent = user_agent
        self.originator = originator
        self.last_call_metadata: ProviderCallMetadata | None = None
        self._completed_call_metadata: list[ProviderCallMetadata] = []
        self._last_response_items: list[dict[str, Any]] = []

    def generate(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
        *,
        conversation: ProviderConversation | None = None,
    ) -> dict[str, Any]:
        """流式调用模型、校验结构化输出并原子追加完整 turn。"""

        self._ensure_configured()
        self.last_call_metadata = None
        self._completed_call_metadata = []
        self._last_response_items = []
        validation_feedback: str | None = None
        successful_input_items: list[dict[str, Any]] = []

        def request_and_validate() -> dict[str, Any]:
            """执行一次模型请求并在同一尝试内校验结构化输出。"""

            nonlocal successful_input_items, validation_feedback
            current_input_items = build_turn_input_items(
                agent_type,
                payload,
                validation_feedback=validation_feedback,
                explicit_cache_breakpoint=self.explicit_cache_breakpoint,
            )
            if self.api_mode == "responses":
                content = self._generate_responses(
                    agent_type,
                    payload,
                    output_model,
                    conversation,
                    current_input_items,
                )
            else:
                content = self._generate_chat_completions(
                    agent_type,
                    output_model,
                    conversation,
                    current_input_items,
                )
            try:
                result = self._parse_output(content, output_model)
            except AgentProviderResponseError as exc:
                validation_feedback = str(exc)[:4000]
                raise
            successful_input_items = current_input_items
            return result

        result = self._run_with_retries(request_and_validate)
        metadata = combine_call_metadata(self._completed_call_metadata)
        if conversation is not None:
            response_items = self._last_response_items or [
                assistant_message_item(output_model.model_validate(result).model_dump_json())
            ]
            try:
                conversation.append_turn(
                    successful_input_items,
                    response_items,
                    response_id=metadata.response_id if metadata is not None else None,
                )
            except ValueError as exc:
                raise AgentProviderResponseError(f"invalid conversation response items: {exc}") from exc
            if metadata is not None:
                metadata = metadata.with_conversation(conversation)
        self.last_call_metadata = metadata
        return result

    def exchange(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
        *,
        conversation: ProviderConversation,
        pending_turn: PendingProviderTurn,
        tools: tuple[ProviderToolDefinition, ...] = (),
    ) -> ProviderExchangeResult:
        """执行一次 Responses 交换，允许工具-only response。

        本方法不执行工具，也不修改 `conversation` / `pending_turn`；Platform API
        或通用 runner 负责执行 Tool Gateway、追加 output 并最终提交逻辑 turn。
        """

        self._ensure_configured()
        if self.api_mode != "responses":
            raise AgentProviderResponseError(
                "tool-capable exchange requires Responses API mode"
            )
        def request_once() -> ProviderExchangeResult:
            return exchange_responses(
                self,
                agent_type,
                payload,
                output_model,
                conversation,
                pending_turn,
                tools=tools,
            )

        return self._run_with_retries(request_once)

    def _generate_responses(
        self, agent_type: str, payload: BaseModel,
        output_model: type[BaseModel],
        conversation: ProviderConversation | None,
        current_input_items: list[dict[str, Any]],
    ) -> str:
        """以 SSE 调用 Responses API 并保存完整有序 output items。"""

        result = generate_responses(
            self,
            agent_type,
            payload,
            output_model,
            conversation,
            current_input_items,
        )
        if result.metadata is not None:
            self._completed_call_metadata.append(result.metadata)
        self._last_response_items = result.response_items
        return result.content

    def _generate_chat_completions(
        self, agent_type: str,
        output_model: type[BaseModel],
        conversation: ProviderConversation | None,
        current_input_items: list[dict[str, Any]],
    ) -> str:
        """以 SSE 兼容仍只提供 Chat Completions 的服务。"""

        return generate_chat_completions(
            self,
            agent_type,
            output_model,
            conversation,
            current_input_items,
        )

    def _post_sse(
        self,
        path: str,
        body: dict[str, Any],
        handle_event: Callable[[dict[str, Any]], None],
        conversation: ProviderConversation | None,
    ) -> None:
        """发送流式请求，逐个解析 data-only SSE 事件。"""

        post_sse(
            endpoint=resolve_endpoint(self.api_base, path),
            body=body,
            headers=build_request_headers(
                api_key=self.api_key,
                user_agent=self.user_agent,
                originator=self.originator,
                conversation=conversation,
            ),
            timeout_seconds=self.timeout_seconds,
            handle_event=handle_event,
            urlopen=request.urlopen,
        )

    def _run_with_retries(self, operation: Callable[[], T]) -> T:
        """对瞬时请求错误和无效结构化响应执行有界指数退避重试。"""

        return run_with_retries(
            operation,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
            sleep=time.sleep,
        )

    def _ensure_configured(self) -> None:
        """拒绝缺少真实外部模型配置的调用。"""

        if not self.api_base or not self.api_key or not self.model_name:
            raise MissingProviderConfigurationError(
                "openai_compatible provider requires CLOUDHELM_LLM_API_BASE, "
                "CLOUDHELM_LLM_MODEL and CLOUDHELM_LLM_API_KEY"
            )

    @staticmethod
    def _parse_output(content: str, output_model: type[BaseModel]) -> dict[str, Any]:
        """解析并用调用方指定的 Pydantic 模型再次校验。"""

        return parse_structured_output(content, output_model)
