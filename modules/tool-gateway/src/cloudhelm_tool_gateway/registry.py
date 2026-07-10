"""工具注册表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from cloudhelm_tool_gateway.policies import ToolPolicy
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel

ToolHandler = Callable[[BaseModel, ToolPolicy], dict[str, Any]]


@dataclass(frozen=True)
class ToolDeclaration:
    """单个工具声明。

    字段说明:
        name: 全局唯一工具名，例如 `repo.read_file`。
        input_model: Pydantic 参数模型，执行前必须校验。
        risk_level: 默认风险等级；L3/L4 在 M5 只生成审批，不执行。
        handler: 已通过策略校验后执行的本地工具函数。
    """

    name: str
    description: str
    input_model: type[BaseModel]
    risk_level: RiskLevel
    requires_approval: bool
    audit_fields: tuple[str, ...]
    handler: ToolHandler
    allowed_agent_types: tuple[str, ...] = ()
    allow_system_call: bool = True

    def public_dict(self) -> dict[str, Any]:
        """返回可暴露给控制台或 Agent 的工具声明。"""

        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "audit_fields": list(self.audit_fields),
            "allowed_agent_types": list(self.allowed_agent_types),
            "allow_system_call": self.allow_system_call,
            "arguments_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """只负责注册和查找工具声明。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDeclaration] = {}

    def register(self, declaration: ToolDeclaration) -> None:
        """注册工具，重复名称直接拒绝。"""

        if declaration.name in self._tools:
            raise ValueError(f"工具已注册：{declaration.name}")
        self._tools[declaration.name] = declaration

    def get(self, name: str) -> ToolDeclaration | None:
        """按名称读取工具声明。"""

        return self._tools.get(name)

    def list_tools(self) -> list[ToolDeclaration]:
        """按名称排序列出工具。"""

        return [self._tools[name] for name in sorted(self._tools)]
