"""DevelopmentPlan ORM 模型。"""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DevelopmentPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Planner Agent 输出的开发计划。

    只保存任务图、execution recipe 引用、风险和审查状态。M6 消费已审批计划
    时仍须经过 Tool Gateway、精确 recipe 门禁和审计，计划记录本身不执行副作用。
    """

    __tablename__ = "development_plans"
    __table_args__ = (
        Index("ix_development_plans_task_status", "task_id", "status"),
        Index("ix_development_plans_project_id", "project_id"),
        Index("ix_development_plans_design", "technical_design_id"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="冗余项目 ID，便于控制台按项目查询。",
    )
    technical_design_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("technical_designs.id", ondelete="CASCADE"),
        nullable=False,
        comment="关联技术设计 ID。",
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, comment="开发计划摘要。")
    steps_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="开发任务图步骤 JSON 数组。",
    )
    risks_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="开发计划风险 JSON 数组。",
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="开发计划状态。")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="开发计划版本。")
    created_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="创建该计划的 Planner AgentRun。",
    )
