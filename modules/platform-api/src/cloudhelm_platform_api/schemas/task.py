"""Task API DTO。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import OrmModel, RiskLevel, TaskStatus


class TaskCreate(BaseModel):
    """创建 Task 的请求体。"""

    project_id: UUID = Field(description="所属项目 ID，必须已存在。")
    title: str = Field(min_length=1, max_length=160, description="任务标题。")
    description: str = Field(min_length=1, description="任务描述。")
    source_type: str = Field(default="manual", min_length=1, description="任务来源类型。")
    source_ref: str | None = Field(default=None, description="来源引用。")
    risk_level: RiskLevel = Field(default=RiskLevel.L0, description="任务初始风险等级。")
    created_by: str = Field(default="user", min_length=1, description="创建人或组件。")


class TaskRead(OrmModel):
    """Task 响应结构。"""

    id: UUID
    project_id: UUID
    title: str
    description: str
    source_type: str
    source_ref: str | None
    status: TaskStatus
    risk_level: RiskLevel
    current_phase: str
    created_by: str
    created_at: datetime
    updated_at: datetime
