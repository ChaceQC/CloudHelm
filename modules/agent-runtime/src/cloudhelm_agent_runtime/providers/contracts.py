"""Agent Provider 调用元数据与 Codex 风格会话上下文。

本模块只保存 Responses API 可重放的结构，不暴露隐藏思维链明文。模型返回
的 reasoning item 仅保留 summary、可选 content 与 encrypted_content；当
`store=false` 时移除服务端 item id，确保下一轮可以按完整前缀重新发送。
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

from cloudhelm_agent_runtime.providers.usage import (
    ProviderCallMetadata,
    ProviderRequestUsage,
)

ConversationSource = Literal["root", "subagent"]

MESSAGE_ROLES = {"system", "developer", "user", "assistant"}
CALL_ITEM_TYPES = {"function_call", "custom_tool_call"}
CALL_OUTPUT_ITEM_TYPES = {"function_call_output", "custom_tool_call_output"}


@dataclass(slots=True)
class ProviderConversation:
    """Codex 风格 ResponseItem 历史，可由调用方跨请求持久化。

    普通 Agent 角色切换继续使用同一个 root conversation。只有显式创建
    subagent 时，调用方才传入新的 `conversation_id` 和父会话元数据。
    """

    conversation_id: str
    items: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    last_response_id: str | None = None
    prompt_cache_key: str | None = None
    source_type: ConversationSource = "root"
    parent_conversation_id: str | None = None
    agent_role: str | None = None
    depth: int = 0

    def append_turn(
        self,
        input_items: dict[str, Any] | list[dict[str, Any]],
        response_items: list[dict[str, Any]],
        *,
        response_id: str | None = None,
    ) -> None:
        """在输出通过本地 schema 后，原子追加 user 与完整模型输出项。

        参数:
            input_items: 当前轮新增的 role/developer/user 等输入项。
            response_items: 模型按顺序返回的 reasoning、tool call、message 等项。
            response_id: 供应商 Responses response id，仅用于审计。

        异常:
            ValueError: item 结构非法，或工具结果找不到此前对应 call。
        """

        normalized_inputs = _normalize_item_list(input_items)
        normalized_response = [normalize_response_item(item) for item in response_items]
        prospective_items = [*self.items, *normalized_inputs, *normalized_response]
        validate_conversation_items(prospective_items)
        self.items = deepcopy(prospective_items)
        self.turn_count += 1
        self.last_response_id = response_id

    def append_context_item(self, item: dict[str, Any]) -> None:
        """追加审批、子 Agent 通知等非模型 turn 上下文，不增加 turn_count。"""

        normalized = normalize_response_item(item)
        prospective_items = [*self.items, normalized]
        validate_conversation_items(prospective_items)
        self.items = deepcopy(prospective_items)

    def request_input(
        self,
        current_input_items: dict[str, Any] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """返回下一次 Responses 请求的完整前缀副本。"""

        return [*deepcopy(self.items), *_normalize_item_list(current_input_items)]


def user_message_item(text: str, *, cache_breakpoint: bool = False) -> dict[str, Any]:
    """构造与 Codex `ResponseItem::Message` 一致的用户输入。

    `cache_breakpoint=True` 使用 Responses API 的
    `prompt_cache_breakpoint` 标记显式缓存写入位置。该标记必须随历史保存，
    才能在后续 turn 作为只读断点继续匹配缓存前缀。
    """

    return message_item("user", text, cache_breakpoint=cache_breakpoint)


def developer_message_item(text: str) -> dict[str, Any]:
    """构造用于审批、环境和子 Agent 通知的 developer 上下文。"""

    return message_item("developer", text)


def assistant_message_item(text: str) -> dict[str, Any]:
    """在兼容端点未返回 output item 时构造最终助手消息。"""

    return message_item("assistant", text, phase="final_answer", content_type="output_text")


def message_item(
    role: str,
    text: str,
    *,
    phase: str | None = None,
    content_type: str = "input_text",
    cache_breakpoint: bool = False,
) -> dict[str, Any]:
    """构造 Responses message item，并校验角色和内容类型。"""

    if role not in MESSAGE_ROLES:
        raise ValueError(f"unsupported Responses message role: {role}")
    if content_type not in {"input_text", "output_text"}:
        raise ValueError(f"unsupported Responses content type: {content_type}")
    content: dict[str, Any] = {
        "type": content_type,
        "text": text,
    }
    if cache_breakpoint:
        content["prompt_cache_breakpoint"] = {"mode": "explicit"}
    item: dict[str, Any] = {
        "type": "message",
        "role": role,
        "content": [content],
    }
    if phase is not None:
        item["phase"] = phase
    return item


def function_call_output_item(call_id: str, output: str | dict[str, Any] | list[Any]) -> dict[str, Any]:
    """构造 Codex/Responses 使用的 function_call_output item。

    Tool Gateway 返回对象会以确定性 JSON 字符串进入模型上下文，调用方必须
    在调用本函数前完成脱敏。
    """

    if not call_id.strip():
        raise ValueError("function call output requires a non-empty call_id")
    encoded_output = (
        output
        if isinstance(output, str)
        else json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": encoded_output,
    }


def subagent_notification_item(
    *,
    conversation_id: str,
    agent_role: str,
    status: str,
    summary: str,
) -> dict[str, Any]:
    """把子 Agent 最终结果作为结构化通知返回父会话。

    子会话的 encrypted reasoning、tool call 和 tool output 不会复制到父线程。
    """

    payload = {
        "conversation_id": conversation_id,
        "agent_role": agent_role,
        "status": status,
        "summary": summary,
    }
    text = (
        "<subagent_notification>\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "</subagent_notification>"
    )
    return developer_message_item(text)


def normalize_response_item(item: dict[str, Any]) -> dict[str, Any]:
    """规范化一个可重放 ResponseItem。

    Codex 在 `store=false` 时只清除服务端 item id，不删除 function/tool 状态。
    本实现同时移除 OpenAI 内部 passthrough metadata，其他已知和扩展字段原样
    保留，以免丢失工具调用或多模态上下文。
    """

    if not isinstance(item, dict):
        raise ValueError("Responses item must be a JSON object")
    item_type = item.get("type")
    if not isinstance(item_type, str) or not item_type:
        raise ValueError("Responses item requires a non-empty type")

    normalized = deepcopy(item)
    normalized.pop("id", None)
    normalized.pop("internal_chat_message_metadata_passthrough", None)

    if item_type == "message":
        role = normalized.get("role")
        content = normalized.get("content")
        if role not in MESSAGE_ROLES:
            raise ValueError(f"unsupported Responses message role: {role}")
        if not isinstance(content, list):
            raise ValueError("Responses message content must be an array")
        if role == "assistant" and not normalized.get("phase"):
            normalized["phase"] = "final_answer"
    elif item_type == "reasoning":
        summary = normalized.get("summary")
        if summary is None:
            normalized["summary"] = []
        elif not isinstance(summary, list):
            raise ValueError("Responses reasoning summary must be an array")
        encrypted = normalized.get("encrypted_content")
        if encrypted is not None and not isinstance(encrypted, str):
            raise ValueError("Responses encrypted reasoning content must be a string")
    elif item_type in CALL_ITEM_TYPES:
        _require_non_empty_string(normalized, "call_id", item_type)
        _require_non_empty_string(normalized, "name", item_type)
    elif item_type in CALL_OUTPUT_ITEM_TYPES:
        _require_non_empty_string(normalized, "call_id", item_type)
        if "output" not in normalized:
            raise ValueError(f"{item_type} requires output")

    return normalized


def validate_conversation_items(items: list[dict[str, Any]]) -> None:
    """校验工具调用/结果顺序，防止孤立或重复 output 污染后续上下文。"""

    calls: dict[tuple[str, str], int] = {}
    outputs: set[tuple[str, str]] = set()
    for index, raw_item in enumerate(items):
        item = normalize_response_item(raw_item)
        item_type = item["type"]
        if item_type in CALL_ITEM_TYPES:
            family = "function" if item_type == "function_call" else "custom"
            key = (family, item["call_id"])
            if key in calls:
                raise ValueError(f"duplicate {item_type} call_id: {item['call_id']}")
            calls[key] = index
            continue
        if item_type in CALL_OUTPUT_ITEM_TYPES:
            family = "function" if item_type == "function_call_output" else "custom"
            key = (family, item["call_id"])
            if key not in calls:
                raise ValueError(f"{item_type} has no earlier matching call: {item['call_id']}")
            if key in outputs:
                raise ValueError(f"duplicate {item_type} for call_id: {item['call_id']}")
            outputs.add(key)


def fork_items_for_subagent(items: list[dict[str, Any]], *, fork_context: bool) -> list[dict[str, Any]]:
    """按 Codex 规则生成子 Agent 初始历史。

    fresh child 不继承父历史；forked child 只保留 system/developer/user 消息
    与 assistant final answer。Reasoning、工具调用和工具结果属于父线程私有
    执行状态，不能跨线程复制。
    """

    if not fork_context:
        return []
    forked: list[dict[str, Any]] = []
    for raw_item in items:
        item = normalize_response_item(raw_item)
        if item["type"] != "message":
            continue
        role = item.get("role")
        if role in {"system", "developer", "user"}:
            forked.append(item)
        elif role == "assistant" and item.get("phase") == "final_answer":
            forked.append(item)
    return deepcopy(forked)


def _require_non_empty_string(item: dict[str, Any], field_name: str, item_type: str) -> None:
    """校验工具 item 的必填字符串字段。"""

    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{item_type} requires non-empty {field_name}")


def _normalize_item_list(
    items: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把单项或多项输入统一规范化为新列表。"""

    raw_items = [items] if isinstance(items, dict) else items
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("conversation turn requires at least one input item")
    return [normalize_response_item(item) for item in raw_items]
