"""Tool Gateway 调用 DTO。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """CloudHelm 工具风险等级。"""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


ToolExecutionStatus = Literal["succeeded", "failed", "waiting_approval"]


def utc_now() -> datetime:
    """返回 UTC 当前时间，供工具调用结果使用。"""

    return datetime.now(UTC)


class ToolCallRequest(BaseModel):
    """Tool Gateway 统一执行请求。"""

    task_id: UUID = Field(description="所属任务 ID。")
    agent_run_id: UUID | None = Field(default=None, description="触发工具调用的 AgentRun；与 agent_type 必须成对出现。")
    agent_type: str | None = Field(default=None, description="由 Platform API 从 AgentRun 解析的 Agent 类型。")
    tool_name: str = Field(min_length=1, description="工具名称。")
    risk_level: RiskLevel = Field(description="调用方认为的风险等级；必须与注册声明一致。")
    idempotency_key: str = Field(min_length=1, max_length=128, description="任务内幂等键。")
    arguments: dict[str, Any] = Field(default_factory=dict, description="工具参数。")
    reason: str = Field(min_length=1, description="调用原因，用于审计和审批说明。")


class ToolCallResult(BaseModel):
    """Tool Gateway 执行结果。

    `waiting_approval` 代表策略已拦截，调用方应创建 ApprovalRequest，不得
    执行真实工具动作。
    """

    status: ToolExecutionStatus
    summary: str
    result_json: dict[str, Any] | None = None
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    duration_ms: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    requires_approval: bool = False
    approval_reason: str | None = None
    arguments_summary: str
    audit_json: dict[str, Any] = Field(default_factory=dict)
