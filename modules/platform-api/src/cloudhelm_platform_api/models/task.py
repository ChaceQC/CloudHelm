"""Task ORM 模型。"""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """CloudHelm 从需求到部署闭环的核心任务记录。"""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_created_at", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目 ID。",
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="任务标题。")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="任务描述。")
    source_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="任务来源，例如 manual、issue 或 alert。",
    )
    source_ref: Mapped[str | None] = mapped_column(Text, comment="来源引用，例如 issue URL。")
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="任务状态。")
    risk_level: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="L0",
        comment="任务整体风险等级。",
    )
    current_phase: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Orchestrator 当前阶段。",
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False, comment="创建人或组件。")
