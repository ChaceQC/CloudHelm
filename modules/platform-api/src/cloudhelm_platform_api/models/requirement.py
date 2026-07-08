"""RequirementSpec ORM 模型。"""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RequirementSpec(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """结构化需求规格。

    M2 不生成需求，只保存用户或后续 Agent 提供的真实结构化内容，供控制台
    与后续编排读取。
    """

    __tablename__ = "requirement_specs"
    __table_args__ = (
        Index("ix_requirement_specs_task_status", "task_id", "status"),
        Index("ix_requirement_specs_project_id", "project_id"),
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
        comment="冗余项目 ID，便于按项目检索需求。",
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False, comment="需求来源类型。")
    raw_input: Mapped[str] = mapped_column(Text, nullable=False, comment="原始需求输入。")
    user_story: Mapped[str | None] = mapped_column(Text, comment="用户故事描述。")
    constraints_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="约束条件 JSON 数组。",
    )
    acceptance_criteria_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="验收标准 JSON 数组。",
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="需求规格状态。")
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="需求规格版本号。",
    )
