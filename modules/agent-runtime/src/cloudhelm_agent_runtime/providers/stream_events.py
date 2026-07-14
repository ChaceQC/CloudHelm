"""Responses 与 Chat Completions SSE 事件累积器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderRequestError,
    AgentProviderResponseError,
)
from cloudhelm_agent_runtime.providers.http_streaming import extract_responses_text


@dataclass(slots=True)
class ResponsesStreamAccumulator:
    """消费 Responses typed events，并保留最终文本与完成对象。"""

    text_deltas: list[str] = field(default_factory=list)
    final_text: str | None = None
    completed_response: dict[str, Any] | None = None
    response_items: list[dict[str, Any]] = field(default_factory=list)
    _items_by_output_index: dict[int, dict[str, Any]] = field(default_factory=dict)

    def handle(self, event_payload: dict[str, Any]) -> None:
        """处理一个 Responses SSE JSON 对象。"""

        event_type = event_payload.get("type")
        if event_type == "response.output_text.delta":
            delta = event_payload.get("delta")
            if isinstance(delta, str):
                self.text_deltas.append(delta)
            return
        if event_type == "response.output_text.done":
            text = event_payload.get("text")
            if isinstance(text, str):
                self.final_text = text
            return
        if event_type == "response.output_item.done":
            item = event_payload.get("item")
            if isinstance(item, dict):
                output_index = event_payload.get("output_index")
                if isinstance(output_index, int) and output_index >= 0:
                    self._items_by_output_index[output_index] = item
                else:
                    self.response_items.append(item)
            return
        if event_type == "response.completed":
            response_payload = event_payload.get("response")
            if isinstance(response_payload, dict):
                self.completed_response = response_payload
                output = response_payload.get("output")
                if isinstance(output, list):
                    completed_items = [
                        item
                        for item in output
                        if isinstance(item, dict)
                    ]
                    if completed_items:
                        self.response_items = completed_items
                    elif self._items_by_output_index:
                        self.response_items = [
                            self._items_by_output_index[index]
                            for index in sorted(self._items_by_output_index)
                        ]
                elif self._items_by_output_index:
                    self.response_items = [
                        self._items_by_output_index[index]
                        for index in sorted(self._items_by_output_index)
                    ]
            return
        if event_type == "response.failed":
            response_payload = event_payload.get("response")
            detail = response_payload if isinstance(response_payload, dict) else event_payload
            error_payload = detail.get("error") if isinstance(detail, dict) else None
            if isinstance(error_payload, dict) and error_payload.get("code") in {
                "upstream_error",
                "server_error",
                "rate_limit_exceeded",
            }:
                raise AgentProviderRequestError(
                    f"responses API upstream failed: {error_payload.get('message') or error_payload.get('code')}",
                    retryable=True,
                    retry_after_seconds=30,
                )
            raise AgentProviderResponseError(f"responses API stream ended with {event_type}: {detail}")
        if event_type == "response.incomplete":
            response_payload = event_payload.get("response")
            detail = response_payload if isinstance(response_payload, dict) else event_payload
            raise AgentProviderResponseError(f"responses API stream ended with {event_type}: {detail}")
        if event_type == "error":
            _raise_stream_error(event_payload)

    def output_text(self) -> str:
        """校验完成状态并返回最终结构化文本。"""

        text = self.output_text_optional()
        if text is not None:
            return text
        raise AgentProviderResponseError(
            "responses API completed with tool calls but without final output text"
        )

    def output_text_optional(self) -> str | None:
        """返回最终文本；合法工具-only response 返回空值。"""

        if self.completed_response is not None and self.completed_response.get("status") not in {None, "completed"}:
            details = (
                self.completed_response.get("incomplete_details")
                or self.completed_response.get("error")
                or {}
            )
            raise AgentProviderResponseError(f"responses API did not complete: {details}")
        if self.final_text:
            return self.final_text
        if self.text_deltas:
            return "".join(self.text_deltas)
        if self.completed_response is not None:
            try:
                return extract_responses_text(self.completed_response)
            except ValueError as exc:
                if any(
                    item.get("type") in {"function_call", "custom_tool_call"}
                    for item in self.response_items
                ):
                    return None
                raise AgentProviderResponseError(str(exc)) from exc
        raise AgentProviderResponseError("responses API stream ended before response.completed")


@dataclass(slots=True)
class ChatCompletionsStreamAccumulator:
    """消费 Chat Completions chunk 并拼接文本 delta。"""

    text_deltas: list[str] = field(default_factory=list)

    def handle(self, event_payload: dict[str, Any]) -> None:
        """处理一个 Chat Completions SSE JSON 对象。"""

        error_payload = event_payload.get("error")
        if isinstance(error_payload, dict):
            _raise_stream_error({"type": "error", "error": error_payload})
        choices = event_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return
        content = delta.get("content")
        if isinstance(content, str):
            self.text_deltas.append(content)

    def output_text(self) -> str:
        """返回完整文本，拒绝没有内容的完成流。"""

        if not self.text_deltas:
            raise AgentProviderResponseError("chat completions stream is missing message content")
        return "".join(self.text_deltas)


def _raise_stream_error(event_payload: dict[str, Any]) -> None:
    """把流内 error 区分为可重试请求错误或不可恢复响应错误。"""

    nested = event_payload.get("error")
    details = nested if isinstance(nested, dict) else event_payload
    code = details.get("code") or details.get("type") or "stream_error"
    message = details.get("message") or details.get("detail") or "模型流返回错误事件。"
    retryable = bool(details.get("retryable")) or str(code) in {
        "server_error",
        "rate_limit_exceeded",
        "origin_response_timeout",
        "origin_bad_gateway",
    }
    if retryable:
        retry_after = details.get("retry_after")
        raise AgentProviderRequestError(
            f"model API stream error {code}: {message}",
            retryable=True,
            retry_after_seconds=float(retry_after) if isinstance(retry_after, (int, float)) else None,
        )
    raise AgentProviderResponseError(f"model API stream error {code}: {message}")
