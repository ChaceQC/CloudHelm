"""AgentRun ORM 模型。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class AgentRun(UUIDPrimaryKeyMixin, Base):
    """单次 Agent 运行记录。

    保存 M4-M6 角色、工作流幂等身份、结构化输出、conversation/usage 证据和
    失败终态；未校验自然语言不作为核心业务对象持久化。
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_task_status", "task_id", "status"),
        Index("ix_agent_runs_started_at", "started_at"),
        Index("ix_agent_runs_conversation_turn", "conversation_id", "conversation_turn"),
        Index(
            "ix_agent_runs_task_workflow_attempt",
            "task_id",
            "workflow_step",
            "attempt",
        ),
        Index(
            "ux_agent_runs_task_idempotency",
            "task_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ux_agent_runs_task_active_workflow",
            "task_id",
            unique=True,
            postgresql_where=text(
                "workflow_step IS NOT NULL "
                "AND status IN ('pending', 'running')"
            ),
        ),
        CheckConstraint(
            "attempt IS NULL OR attempt > 0",
            name="ck_agent_runs_attempt_positive",
        ),
        CheckConstraint(
            "("
            "workflow_step IS NULL AND attempt IS NULL AND idempotency_key IS NULL"
            ") OR ("
            "workflow_step IS NOT NULL AND attempt IS NOT NULL "
            "AND idempotency_key IS NOT NULL"
            ")",
            name="ck_agent_runs_workflow_identity",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete="SET NULL"),
        comment="本次运行所属 root 或显式 subagent conversation。",
    )
    conversation_turn: Mapped[int | None] = mapped_column(
        Integer,
        comment="本次成功输出提交后的 conversation turn。",
    )
    agent_type: Mapped[str] = mapped_column(Text, nullable=False, comment="Agent 类型。")
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="运行状态。")
    workflow_step: Mapped[str | None] = mapped_column(
        Text,
        comment="M6 工作流步骤，例如 run_coder 或 run_tester。",
    )
    attempt: Mapped[int | None] = mapped_column(
        Integer,
        comment="同一任务工作流步骤的重试序号，从 1 开始。",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        Text,
        comment="任务内 Agent 步骤幂等键。",
    )
    model_name: Mapped[str | None] = mapped_column(Text, comment="使用的模型名称。")
    prompt_hash: Mapped[str | None] = mapped_column(Text, comment="Prompt 版本或哈希。")
    summary: Mapped[str | None] = mapped_column(Text, comment="结构化输出或失败摘要。")
    structured_output_type: Mapped[str | None] = mapped_column(Text, comment="结构化输出类型。")
    structured_output_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        comment="通过 schema 校验后的结构化输出 JSON。",
    )
    error_code: Mapped[str | None] = mapped_column(Text, comment="失败错误码。")
    error_message: Mapped[str | None] = mapped_column(Text, comment="失败错误信息。")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="供应商 usage 返回的真实缓存输入 token。",
    )
    provider_request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="本次 AgentRun 内已完成并返回 usage 的模型请求次数。",
    )
    provider_requests: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="每次已完成供应商请求的原始 token/cache usage 证据。",
    )
    provider_response_id: Mapped[str | None] = mapped_column(
        Text,
        comment="最后一次供应商 Responses response id。",
    )
    prompt_cache_key: Mapped[str | None] = mapped_column(
        Text,
        comment="供应商 Prompt Cache 路由键。",
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("0"),
        comment="本次运行估算成本。",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="运行开始时间。",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="运行结束时间。",
    )
