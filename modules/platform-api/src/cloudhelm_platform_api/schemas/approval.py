"""ApprovalRequest API DTO。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import ApprovalStatus, OrmModel, RiskLevel


class ApprovalRequestCreate(BaseModel):
    """开发/内部联调用审批创建请求体。"""

    action: str = Field(min_length=1, description="申请执行的动作。")
    risk_level: RiskLevel = Field(description="动作风险等级。")
    reason: str = Field(min_length=1, description="申请原因。")
    requested_by_agent_run_id: UUID | None = Field(default=None, description="发起审批的 AgentRun。")


class ApprovalRequestRead(OrmModel):
    """审批请求响应结构。"""

    id: UUID
    task_id: UUID
    action: str
    risk_level: RiskLevel
    reason: str
    status: ApprovalStatus
    requested_by_agent_run_id: UUID | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
