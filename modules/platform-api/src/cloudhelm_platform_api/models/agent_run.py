"""AgentRun ORM 模型。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class AgentRun(UUIDPrimaryKeyMixin, Base):
    """单次 Agent 运行记录。

    M4 增加结构化输出摘要和错误字段。AgentRun 只记录执行结果，不保存
    未校验自然语言作为核心业务对象。
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_task_status", "task_id", "status"),
        Index("ix_agent_runs_started_at", "started_at"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    agent_type: Mapped[str] = mapped_column(Text, nullable=False, comment="Agent 类型。")
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="运行状态。")
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
