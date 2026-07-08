"""ApprovalRequest ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    """人工审批请求。

    ApprovalRequest 是 L3/L4 操作和设计/需求审批的审计基础。M2 支持创建、
    通过和拒绝，但不自动触发高风险工具执行。
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_task_status", "task_id", "status"),
        Index("ix_approval_requests_created_at", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    action: Mapped[str] = mapped_column(Text, nullable=False, comment="申请执行的动作。")
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, comment="动作风险等级。")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="申请原因。")
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="审批状态。")
    requested_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="发起审批的 AgentRun。",
    )
    decided_by: Mapped[str | None] = mapped_column(Text, comment="审批决策人。")
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="审批决策时间。",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="审批创建时间。",
    )
