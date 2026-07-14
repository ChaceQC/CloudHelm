"""TechnicalDesign ORM 模型。"""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TechnicalDesign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """技术设计记录。

    保存手工提交或 Architect Agent 生成的 ADR、OpenAPI/数据库 schema 草案
    与风险结论；该记录本身不执行迁移或外部工具副作用。
    """

    __tablename__ = "technical_designs"
    __table_args__ = (
        Index("ix_technical_designs_task_status", "task_id", "status"),
        Index("ix_technical_designs_requirement", "requirement_spec_id"),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    requirement_spec_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("requirement_specs.id", ondelete="CASCADE"),
        nullable=False,
        comment="关联需求规格 ID。",
    )
    design_type: Mapped[str] = mapped_column(Text, nullable=False, comment="设计类型。")
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False, comment="设计正文。")
    openapi_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        comment="OpenAPI 草案 JSON。",
    )
    db_schema_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        comment="数据库 schema 草案 JSON。",
    )
    mermaid_diagram: Mapped[str | None] = mapped_column(Text, comment="Mermaid 图。")
    risk_level: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="L0",
        comment="设计涉及的最高风险等级。",
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="设计审批状态。")
    created_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="创建该设计的 AgentRun；M2 可为空。",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="技术设计版本号。",
    )
