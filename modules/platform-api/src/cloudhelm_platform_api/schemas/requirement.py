"""RequirementSpec API DTO。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import OrmModel, ReviewStatus


class RequirementSpecCreate(BaseModel):
    """创建需求规格的请求体。"""

    source_type: str = Field(default="manual", min_length=1, description="需求来源类型。")
    raw_input: str = Field(min_length=1, description="原始需求输入。")
    user_story: str | None = Field(default=None, description="用户故事。")
    constraints_json: list[Any] = Field(default_factory=list, description="约束条件 JSON 数组。")
    acceptance_criteria_json: list[Any] = Field(
        default_factory=list,
        description="验收标准 JSON 数组。",
    )


class RequirementSpecRead(OrmModel):
    """需求规格响应结构。"""

    id: UUID
    task_id: UUID
    project_id: UUID
    source_type: str
    raw_input: str
    user_story: str | None
    constraints_json: list[Any]
    acceptance_criteria_json: list[Any]
    status: ReviewStatus
    version: int
    created_at: datetime
    updated_at: datetime
