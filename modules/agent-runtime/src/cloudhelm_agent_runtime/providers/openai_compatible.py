"""OpenAI 兼容 structured outputs provider。

默认使用 HTTP SSE Responses API。普通 Agent 角色切换复用调用方传入的同一
ProviderConversation；只有显式 subagent conversation 才会发送新的 thread id
以及 parent/subagent headers。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib import request

from pydantic import BaseModel, ValidationError

from cloudhelm_agent_runtime.instructions import build_turn_input_items
from cloudhelm_agent_runtime.providers.base import (
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
    StructuredAgentProvider,
)
from cloudhelm_agent_runtime.providers.contracts import (
    ProviderConversation,
    assistant_message_item,
    normalize_response_item,
)
from cloudhelm_agent_runtime.providers.http_client import (
    DEFAULT_CODEX_ORIGINATOR,
    DEFAULT_CODEX_USER_AGENT,
    build_request_headers,
    post_sse,
    resolve_endpoint,
    validate_header_value,
)
from cloudhelm_agent_runtime.providers.prompt_cache import (
    combine_call_metadata,
    extract_call_metadata,
)
from cloudhelm_agent_runtime.providers.request_payloads import (
    ApiMode,
    ReasoningContext,
    ReasoningEffort,
    ReasoningSummary,
    build_chat_completions_body,
    build_responses_body,
)
from cloudhelm_agent_runtime.providers.stream_events import (
    ChatCompletionsStreamAccumulator, ResponsesStreamAccumulator,
)
from cloudhelm_agent_runtime.providers.usage import ProviderCallMetadata

class OpenAICompatibleProvider(StructuredAgentProvider):
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

    def _generate_responses(
        self, agent_type: str, payload: BaseModel,
        output_model: type[BaseModel],
        conversation: ProviderConversation | None,
        current_input_items: list[dict[str, Any]],
    ) -> str:
        """以 SSE 调用 Responses API 并保存完整有序 output items。"""

        if self.model_name is None:
            raise MissingProviderConfigurationError("model name is missing")
        body, prompt_cache_key = build_responses_body(
            agent_type=agent_type,
            payload=payload,
            output_model=output_model,
            model_name=self.model_name,
            current_input_items=current_input_items,
            conversation=conversation,
            reasoning_effort=self.reasoning_effort,
            reasoning_summary=self.reasoning_summary,
            reasoning_context=self.reasoning_context,
            max_output_tokens=self.max_output_tokens,
            explicit_cache_breakpoint=self.explicit_cache_breakpoint,
        )
        accumulator = ResponsesStreamAccumulator()
        self._post_sse("/v1/responses", body, accumulator.handle, conversation)
        content = accumulator.output_text()
        if accumulator.completed_response is not None:
            self._completed_call_metadata.append(
                extract_call_metadata(accumulator.completed_response, prompt_cache_key)
            )
        try:
            self._last_response_items = [
                normalize_response_item(item)
                for item in accumulator.response_items
            ]
        except ValueError as exc:
            raise AgentProviderResponseError(f"responses API returned invalid output item: {exc}") from exc
        return content

    def _generate_chat_completions(
        self, agent_type: str,
        output_model: type[BaseModel],
        conversation: ProviderConversation | None,
        current_input_items: list[dict[str, Any]],
    ) -> str:
        """以 SSE 兼容仍只提供 Chat Completions 的服务。"""

        if self.model_name is None:
            raise MissingProviderConfigurationError("model name is missing")
        body = build_chat_completions_body(
            agent_type=agent_type,
            output_model=output_model,
            model_name=self.model_name,
            conversation=conversation,
            current_input_items=current_input_items,
            reasoning_effort=self.reasoning_effort,
            max_output_tokens=self.max_output_tokens,
        )
        accumulator = ChatCompletionsStreamAccumulator()
        self._post_sse("/v1/chat/completions", body, accumulator.handle, conversation)
        return accumulator.output_text()

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

    def _run_with_retries(self, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """对瞬时请求错误和无效结构化响应执行有界指数退避重试。"""

        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except AgentProviderRequestError as exc:
                if not exc.retryable or attempt == self.max_attempts:
                    raise
                retry_after_seconds = exc.retry_after_seconds or 0
            except AgentProviderResponseError:
                if attempt == self.max_attempts:
                    raise
                retry_after_seconds = 0
            delay_seconds = max(
                self.retry_backoff_seconds * (2 ** (attempt - 1)),
                retry_after_seconds,
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)
        raise RuntimeError("unreachable provider retry state")

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

        try:
            parsed = json.loads(content)
            return output_model.model_validate(parsed).model_dump(mode="json")
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise AgentProviderResponseError(
                f"structured output validation failed: {exc}"
            ) from exc
