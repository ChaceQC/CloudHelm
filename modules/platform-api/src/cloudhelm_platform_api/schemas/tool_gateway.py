"""Tool Gateway API DTO。"""

from typing import Any
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cloudhelm_platform_api.schemas.common import RiskLevel


class ToolGatewayCallCreate(BaseModel):
    """执行 Tool Gateway 调用的请求体。"""

    model_config = ConfigDict(extra="forbid")

    agent_run_id: UUID | None = Field(default=None, description="触发工具调用且状态必须为 running 的 AgentRun。")
    provider_call_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Responses function/custom call_id。",
    )
    provider_item_type: Literal["function_call", "custom_tool_call"] | None = None
    tool_name: str = Field(min_length=1, description="工具名称。")
    risk_level: RiskLevel = Field(description="工具风险等级，必须与注册声明一致。")
    idempotency_key: str = Field(min_length=1, max_length=128, description="任务内幂等键。")
    arguments: dict[str, Any] = Field(description="工具参数 JSON；无参数工具也必须显式传入空对象。")
    reason: str = Field(min_length=1, description="调用原因或审批说明。")

    @model_validator(mode="after")
    def validate_provider_call_pair(self) -> "ToolGatewayCallCreate":
        """供应商 call_id 与 item type 必须成对出现。"""

        if (self.provider_call_id is None) != (self.provider_item_type is None):
            raise ValueError("provider_call_id and provider_item_type must be provided together")
        return self


class ToolDeclarationRead(BaseModel):
    """控制台和 Agent 可见的工具声明。"""

    name: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool
    audit_fields: list[str]
    allowed_agent_types: list[str]
    allow_system_call: bool
    bound_arguments: list[str]
    arguments_schema: dict[str, Any]
    provider_arguments_schema: dict[str, Any]
    result_schema: dict[str, Any]
