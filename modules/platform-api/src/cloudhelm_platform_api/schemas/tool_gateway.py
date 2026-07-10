"""Tool Gateway API DTO。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import RiskLevel


class ToolGatewayCallCreate(BaseModel):
    """执行 Tool Gateway 调用的请求体。"""

    agent_run_id: UUID | None = Field(default=None, description="触发工具调用且状态必须为 running 的 AgentRun。")
    tool_name: str = Field(min_length=1, description="工具名称。")
    risk_level: RiskLevel = Field(description="工具风险等级，必须与注册声明一致。")
    idempotency_key: str = Field(min_length=1, max_length=128, description="任务内幂等键。")
    arguments: dict[str, Any] = Field(default_factory=dict, description="工具参数 JSON。")
    reason: str = Field(min_length=1, description="调用原因或审批说明。")


class ToolDeclarationRead(BaseModel):
    """控制台和 Agent 可见的工具声明。"""

    name: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool
    audit_fields: list[str]
    allowed_agent_types: list[str]
    allow_system_call: bool
    arguments_schema: dict[str, Any]
