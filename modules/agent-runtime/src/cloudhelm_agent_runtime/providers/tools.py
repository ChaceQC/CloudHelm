"""Codex/Responses 风格工具声明、调用与结果契约。

本模块不执行工具。模型返回的调用必须由 Platform API 交给 Tool Gateway，
完成权限、审批、审计和脱敏后，再构造 `function_call_output` 回到会话。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cloudhelm_agent_runtime.providers.contracts import function_call_output_item


@dataclass(frozen=True, slots=True)
class ProviderToolDefinition:
    """可发送给 Responses API 的 function tool 声明。"""

    name: str
    description: str
    parameters: dict[str, Any]
    strict: bool = True

    def to_responses_json(self) -> dict[str, Any]:
        """转换为 Responses `tools` 数组项。"""

        if not self.name.strip():
            raise ValueError("tool name cannot be empty")
        if not self.description.strip():
            raise ValueError(f"tool {self.name} requires a description")
        if self.parameters.get("type") != "object":
            raise ValueError(f"tool {self.name} parameters must be an object JSON Schema")
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": self.strict,
        }


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    """模型返回的 function/custom tool call。"""

    call_id: str
    name: str
    arguments: dict[str, Any]
    item_type: str = "function_call"

    @classmethod
    def from_response_item(cls, item: dict[str, Any]) -> ProviderToolCall:
        """解析 Responses 调用项，拒绝非对象参数或无 call_id。"""

        item_type = item.get("type")
        if item_type not in {"function_call", "custom_tool_call"}:
            raise ValueError(f"unsupported tool call item type: {item_type}")
        call_id = item.get("call_id")
        name = item.get("name")
        raw_arguments = item.get("arguments") if item_type == "function_call" else item.get("input")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ValueError(f"{item_type} requires call_id")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{item_type} requires name")
        if not isinstance(raw_arguments, str):
            raise ValueError(f"{item_type} arguments must be a JSON string")
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{item_type} arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ValueError(f"{item_type} arguments must decode to an object")
        return cls(
            call_id=call_id,
            name=name,
            arguments=arguments,
            item_type=item_type,
        )


def collect_tool_calls(response_items: list[dict[str, Any]]) -> list[ProviderToolCall]:
    """按响应顺序提取模型工具调用。"""

    return [
        ProviderToolCall.from_response_item(item)
        for item in response_items
        if item.get("type") in {"function_call", "custom_tool_call"}
    ]


def tool_result_item(
    call: ProviderToolCall,
    *,
    status: str,
    result: dict[str, Any],
    error_code: str | None = None,
) -> dict[str, Any]:
    """把已脱敏 Tool Gateway 结果转换为可回放 output item。"""

    payload = {
        "status": status,
        "result": result,
        "error_code": error_code,
    }
    if call.item_type == "custom_tool_call":
        return {
            "type": "custom_tool_call_output",
            "call_id": call.call_id,
            "name": call.name,
            "output": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    return function_call_output_item(call.call_id, payload)
