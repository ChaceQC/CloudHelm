"""ToolCall API DTO。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.schemas.common import RiskLevel, ToolCallStatus


class ToolCallCreate(BaseModel):
    """开发/内部联调用 ToolCall 创建请求体。

    M2 仅记录工具调用元数据和参数摘要，不执行真实工具调用。审计字段由
    服务端生成，调用方不得提交或覆盖。
    """

    model_config = ConfigDict(extra="forbid")

    agent_run_id: UUID | None = Field(default=None, description="关联 AgentRun。")
    tool_name: str = Field(min_length=1, description="工具名称。")
    risk_level: RiskLevel = Field(description="工具风险等级。")
    arguments_json: dict[str, Any] = Field(default_factory=dict, description="工具参数 JSON。")
    result_json: dict[str, Any] | None = Field(default=None, description="工具结果 JSON。")
    status: ToolCallStatus = Field(default=ToolCallStatus.PENDING, description="工具调用状态。")
    approval_id: UUID | None = Field(default=None, description="关联审批请求。")
    idempotency_key: str | None = Field(default=None, description="任务内幂等键。")
    arguments_summary: str | None = Field(default=None, description="参数摘要。")
    result_summary: str | None = Field(default=None, description="结果摘要。")
    stdout_summary: str | None = Field(default=None, description="stdout 摘要。")
    stderr_summary: str | None = Field(default=None, description="stderr 摘要。")
    duration_ms: int | None = Field(default=None, ge=0, description="执行耗时毫秒。")
    error_code: str | None = Field(default=None, description="失败错误码。")


class ToolCallRead(BaseModel):
    """ToolCall 响应结构。

    响应只暴露 `arguments_summary` 和脱敏审计字段，避免把参数正文或凭据
    原样展示给控制台。数据库也只保存脱敏后的参数快照。
    """

    id: UUID
    task_id: UUID
    agent_run_id: UUID | None
    tool_name: str
    risk_level: RiskLevel
    arguments_summary: str
    audit_json: dict[str, Any]
    result_json: dict[str, Any] | None
    result_summary: str | None
    stdout_summary: str | None
    stderr_summary: str | None
    duration_ms: int | None
    error_code: str | None
    status: ToolCallStatus
    approval_id: UUID | None
    idempotency_key: str | None
    started_at: datetime
    finished_at: datetime | None


def summarize_arguments(arguments: dict[str, Any], max_length: int = 240) -> str:
    """生成参数摘要，避免 API 响应泄露完整参数。

    该函数仅用于展示，不修改数据库中真实审计字段。
    """

    keys = ", ".join(sorted(arguments.keys())) or "empty"
    summary = f"keys=[{keys}]"
    return summary if len(summary) <= max_length else f"{summary[: max_length - 3]}..."


def tool_call_to_read(tool_call: ToolCall) -> ToolCallRead:
    """将 ORM ToolCall 转为响应 DTO。"""

    return ToolCallRead(
        id=tool_call.id,
        task_id=tool_call.task_id,
        agent_run_id=tool_call.agent_run_id,
        tool_name=tool_call.tool_name,
        risk_level=RiskLevel(tool_call.risk_level),
        arguments_summary=tool_call.arguments_summary or summarize_arguments(tool_call.arguments_json),
        audit_json=tool_call.audit_json,
        result_json=tool_call.result_json,
        result_summary=tool_call.result_summary,
        stdout_summary=tool_call.stdout_summary,
        stderr_summary=tool_call.stderr_summary,
        duration_ms=tool_call.duration_ms,
        error_code=tool_call.error_code,
        status=ToolCallStatus(tool_call.status),
        approval_id=tool_call.approval_id,
        idempotency_key=tool_call.idempotency_key,
        started_at=tool_call.started_at,
        finished_at=tool_call.finished_at,
    )
