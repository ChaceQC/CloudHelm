"""ToolCall ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class ToolCall(UUIDPrimaryKeyMixin, Base):
    """工具调用记录。

    M2 记录工具调用元数据和参数 JSON，真实执行、审批拦截和 MCP 路由仍属于
    后续 Tool Gateway 阶段。
    """

    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_task_status", "task_id", "status"),
        Index("ix_tool_calls_agent_run_id", "agent_run_id"),
        Index("ix_tool_calls_started_at", "started_at"),
        Index(
            "ux_tool_calls_task_idempotency",
            "task_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="触发该工具调用的 AgentRun。",
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False, comment="工具名称。")
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, comment="工具风险等级。")
    arguments_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="工具参数 JSON；API 响应默认只暴露摘要。",
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="工具结果 JSON。")
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="工具调用状态。")
    idempotency_key: Mapped[str | None] = mapped_column(Text, comment="任务内幂等键。")
    arguments_summary: Mapped[str | None] = mapped_column(Text, comment="脱敏参数摘要。")
    result_summary: Mapped[str | None] = mapped_column(Text, comment="工具结果摘要。")
    stdout_summary: Mapped[str | None] = mapped_column(Text, comment="stdout 截断摘要。")
    stderr_summary: Mapped[str | None] = mapped_column(Text, comment="stderr 截断摘要。")
    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="工具调用耗时毫秒数。")
    error_code: Mapped[str | None] = mapped_column(Text, comment="失败错误码。")
    approval_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        comment="关联审批请求 ID。",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="调用开始时间。",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="调用结束时间。",
    )
