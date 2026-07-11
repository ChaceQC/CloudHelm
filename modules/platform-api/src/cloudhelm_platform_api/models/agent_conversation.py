"""Task root / subagent conversation ORM 模型。"""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Codex 风格持久化会话。

    每个 Task 只有一个 root conversation；Requirement、Architect、Planner 等
    普通角色共享该记录。只有显式 spawn subagent 才创建带 parent 的 child
    conversation。
    """

    __tablename__ = "agent_conversations"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('root', 'subagent')",
            name="ck_agent_conversations_source_type",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'failed', 'cancelled')",
            name="ck_agent_conversations_status",
        ),
        CheckConstraint(
            "fork_mode IS NULL OR fork_mode IN ('fresh', 'full_history')",
            name="ck_agent_conversations_fork_mode",
        ),
        CheckConstraint(
            "("
            "source_type = 'root' AND parent_conversation_id IS NULL "
            "AND spawned_by_agent_run_id IS NULL AND agent_role IS NULL "
            "AND objective IS NULL AND fork_mode IS NULL AND depth = 0"
            ") OR ("
            "source_type = 'subagent' AND parent_conversation_id IS NOT NULL "
            "AND spawned_by_agent_run_id IS NOT NULL AND agent_role IS NOT NULL "
            "AND objective IS NOT NULL AND fork_mode IS NOT NULL AND depth > 0"
            ")",
            name="ck_agent_conversations_source_fields",
        ),
        CheckConstraint("depth >= 0", name="ck_agent_conversations_depth"),
        UniqueConstraint(
            "prompt_cache_key",
            name="uq_agent_conversations_prompt_cache_key",
        ),
        Index(
            "ux_agent_conversations_task_root",
            "task_id",
            unique=True,
            postgresql_where=text("source_type = 'root'"),
        ),
        Index(
            "ix_agent_conversations_parent_status",
            "parent_conversation_id",
            "status",
        ),
        Index("ix_agent_conversations_task_status", "task_id", "status"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属 Task；普通角色共享同一 root conversation。",
    )
    parent_conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        comment="显式 subagent 的父会话；root 为 NULL。",
    )
    spawned_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "agent_runs.id",
            ondelete="SET NULL",
            name="fk_agent_conversations_spawned_by_agent_run_id",
            use_alter=True,
        ),
        comment="显式创建该 subagent 的父 AgentRun。",
    )
    source_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="root",
        comment="会话来源：root 或 subagent。",
    )
    agent_role: Mapped[str | None] = mapped_column(
        Text,
        comment="subagent 角色；root 不绑定 Requirement/Architect 等普通角色。",
    )
    nickname: Mapped[str | None] = mapped_column(
        Text,
        comment="控制台展示用子 Agent 名称。",
    )
    objective: Mapped[str | None] = mapped_column(
        Text,
        comment="显式 spawn 指定的唯一子目标；root 为 NULL。",
    )
    depth: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="从 root 开始的 subagent 深度。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        comment="会话生命周期状态。",
    )
    fork_mode: Mapped[str | None] = mapped_column(
        Text,
        comment="子会话上下文模式：fresh 或 full_history。",
    )
    provider_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Provider 名称。",
    )
    model_name: Mapped[str | None] = mapped_column(
        Text,
        comment="模型名称；本地规则 Provider 也记录其稳定版本名。",
    )
    prompt_cache_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="供应商 Prompt Cache 路由键。",
    )
    items_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="可重放的完整 ResponseItem 数组，包含 encrypted reasoning 和工具项。",
    )
    turn_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已成功提交的模型 turn 数。",
    )
    last_response_id: Mapped[str | None] = mapped_column(
        Text,
        comment="最近一次供应商 Responses response id。",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="子会话完成、失败或取消时间。",
    )
