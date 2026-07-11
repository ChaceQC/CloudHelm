"""OpenAI Responses / Chat Completions 请求体构造。

把稳定基础 prompt、完整会话前缀和 reasoning 配置集中在纯函数中，便于用
白盒测试直接比较相邻请求的 input prefix。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from cloudhelm_agent_runtime.instructions import base_instructions
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.output_schema import (
    STABLE_OUTPUT_SCHEMA_NAME,
    stable_output_schema,
)
from cloudhelm_agent_runtime.providers.prompt_cache import build_prompt_cache_key

ApiMode = Literal["responses", "chat_completions"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
ReasoningSummary = Literal["auto", "concise", "detailed"]
ReasoningContext = Literal["current_turn", "all_turns"]


def build_responses_body(
    *,
    agent_type: str,
    payload: BaseModel,
    output_model: type[BaseModel],
    model_name: str,
    current_input_items: list[dict[str, Any]],
    conversation: ProviderConversation | None,
    reasoning_effort: ReasoningEffort,
    reasoning_summary: ReasoningSummary | None,
    reasoning_context: ReasoningContext | None,
    max_output_tokens: int,
    explicit_cache_breakpoint: bool,
) -> tuple[dict[str, Any], str]:
    """构造 Responses 请求体并返回实际 prompt cache key。"""

    prompt_cache_key = (
        conversation.prompt_cache_key
        if conversation is not None and conversation.prompt_cache_key
        else build_prompt_cache_key(
            model_name,
            agent_type,
            payload,
            conversation.conversation_id if conversation is not None else None,
        )
    )
    reasoning: dict[str, Any] = {"effort": reasoning_effort}
    if reasoning_summary is not None:
        reasoning["summary"] = reasoning_summary
    if reasoning_context is not None:
        reasoning["context"] = reasoning_context

    body = {
        "model": model_name,
        "instructions": base_instructions(),
        "input": (
            conversation.request_input(current_input_items)
            if conversation is not None
            else current_input_items
        ),
        "reasoning": reasoning,
        "text": {
            "format": {
                "type": "json_schema",
                "name": STABLE_OUTPUT_SCHEMA_NAME,
                "strict": False,
                "schema": stable_output_schema(output_model),
            }
        },
        "max_output_tokens": max_output_tokens,
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": prompt_cache_key,
    }
    if explicit_cache_breakpoint:
        body["prompt_cache_options"] = {"mode": "explicit"}
    return body, prompt_cache_key


def build_chat_completions_body(
    *,
    agent_type: str,
    output_model: type[BaseModel],
    model_name: str,
    conversation: ProviderConversation | None,
    current_input_items: list[dict[str, Any]],
    reasoning_effort: ReasoningEffort,
    max_output_tokens: int,
) -> dict[str, Any]:
    """构造旧 Chat Completions 流式兼容请求体。"""

    messages = [{"role": "system", "content": base_instructions()}]
    if conversation is not None:
        messages.extend(_chat_messages(conversation))
    messages.extend(_items_to_chat_messages(current_input_items))
    return {
        "model": model_name,
        "messages": messages,
        "reasoning_effort": reasoning_effort,
        "max_completion_tokens": max_output_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"cloudhelm_{agent_type}_output",
                "strict": False,
                "schema": output_model.model_json_schema(),
            },
        },
        "stream": True,
    }


def _chat_messages(conversation: ProviderConversation) -> list[dict[str, str]]:
    """把 Responses message items 投影为 Chat Completions 历史。"""

    return _items_to_chat_messages(conversation.items)


def _items_to_chat_messages(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """把一组 Responses message items 投影为 Chat Completions 历史。"""

    messages: list[dict[str, str]] = []
    for item in items:
        if item.get("type") != "message" or item.get("role") not in {
            "system",
            "developer",
            "user",
            "assistant",
        }:
            continue
        text = "".join(
            str(content.get("text") or "")
            for content in item.get("content", [])
            if isinstance(content, dict)
        )
        role = "system" if item["role"] == "developer" else str(item["role"])
        messages.append({"role": role, "content": text})
    return messages
