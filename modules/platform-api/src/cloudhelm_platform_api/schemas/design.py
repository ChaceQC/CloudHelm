"""TechnicalDesign API DTO。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import OrmModel, ReviewStatus, RiskLevel


class TechnicalDesignCreate(BaseModel):
    """创建技术设计的请求体。"""

    requirement_spec_id: UUID = Field(description="关联需求规格 ID。")
    design_type: str = Field(default="mvp", min_length=1, description="设计类型。")
    content_markdown: str = Field(min_length=1, description="技术设计正文。")
    openapi_json: dict[str, Any] | None = Field(default=None, description="OpenAPI 草案 JSON。")
    db_schema_json: dict[str, Any] | None = Field(default=None, description="数据库 schema 草案 JSON。")
    mermaid_diagram: str | None = Field(default=None, description="Mermaid 图。")
    risk_level: RiskLevel = Field(default=RiskLevel.L0, description="设计涉及风险等级。")
    created_by_agent_run_id: UUID | None = Field(default=None, description="创建该设计的 AgentRun。")


class TechnicalDesignRead(OrmModel):
    """技术设计响应结构。"""

    id: UUID
    task_id: UUID
    requirement_spec_id: UUID
    design_type: str
    content_markdown: str
    openapi_json: dict[str, Any] | None
    db_schema_json: dict[str, Any] | None
    mermaid_diagram: str | None
    risk_level: RiskLevel
    status: ReviewStatus
    created_by_agent_run_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
