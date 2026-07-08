"""EventLog ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class EventLog(UUIDPrimaryKeyMixin, Base):
    """追加式事件日志。

    事件日志记录 Task、Requirement、Design、Approval 等状态变化。service 层
    必须在同一事务内同时写业务记录与 EventLog，避免 UI 时间线与真实状态
    不一致。
    """

    __tablename__ = "event_logs"
    __table_args__ = (
        Index("ix_event_logs_task_created_at", "task_id", "created_at"),
        Index("ix_event_logs_event_type", "event_type"),
    )

    task_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        comment="事件所属任务；ProjectCreated 可为空。",
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False, comment="事件类型。")
    actor_type: Mapped[str] = mapped_column(Text, nullable=False, comment="触发者类型。")
    actor_id: Mapped[str | None] = mapped_column(Text, comment="触发者标识。")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="事件载荷。",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="事件创建时间。",
    )
