"""ToolCall ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class ToolCall(UUIDPrimaryKeyMixin, Base):
    """工具调用记录。

    记录 Tool Gateway 的脱敏参数/结果、安全审计、审批关联、幂等身份和终态。
    M6 Git patch 正文只在执行进程与受控 Artifact 中保留，数据库仅保存安全投影
    及原始内容 SHA-256。
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
        Index(
            "ux_tool_calls_agent_provider_call",
            "agent_run_id",
            "provider_call_id",
            unique=True,
            postgresql_where=text("provider_call_id IS NOT NULL"),
        ),
        CheckConstraint(
            "provider_item_type IS NULL "
            "OR provider_item_type IN ('function_call', 'custom_tool_call')",
            name="ck_tool_calls_provider_item_type",
        ),
        CheckConstraint(
            "("
            "provider_call_id IS NULL AND provider_item_type IS NULL"
            ") OR ("
            "provider_call_id IS NOT NULL AND provider_item_type IS NOT NULL "
            "AND agent_run_id IS NOT NULL"
            ")",
            name="ck_tool_calls_provider_identity",
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
    provider_call_id: Mapped[str | None] = mapped_column(
        Text,
        comment="供应商 function/custom tool call_id。",
    )
    provider_item_type: Mapped[str | None] = mapped_column(
        Text,
        comment="供应商调用项类型：function_call 或 custom_tool_call。",
    )
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, comment="工具风险等级。")
    arguments_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="脱敏后的工具参数 JSON；文件正文只保留长度和 hash。",
    )
    audit_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Tool Gateway 生成的参数 hash、主体、风险、幂等键和终态审计字段。",
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
