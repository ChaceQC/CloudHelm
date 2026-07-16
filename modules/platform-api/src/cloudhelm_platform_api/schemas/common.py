"""API 通用 DTO、枚举和分页结构。"""

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(str, Enum):
    """CloudHelm 工具和任务风险等级。"""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class TaskStatus(str, Enum):
    """任务状态枚举，与设计文档数据层保持一致。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class ReviewStatus(str, Enum):
    """需求和技术设计的人工评审状态。"""

    DRAFT = "draft"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class DevelopmentPlanStatus(str, Enum):
    """DevelopmentPlan 审查状态。"""

    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class AgentRunStatus(str, Enum):
    """AgentRun 状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolCallStatus(str, Enum):
    """ToolCall 状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLED = "cancelled"


class ApprovalStatus(str, Enum):
    """ApprovalRequest 状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OrmModel(BaseModel):
    """支持从 SQLAlchemy ORM 对象读取字段的 DTO 基类。"""

    model_config = ConfigDict(from_attributes=True)


class PageInfo(BaseModel):
    """分页元数据。

    M2 使用 offset cursor 的最小实现，后续如需高并发滚动查询可升级为
    基于 `created_at,id` 的稳定游标。
    """

    limit: int = Field(ge=1, le=100, description="本次最多返回条数。")
    next_cursor: str | None = Field(default=None, description="下一页游标；为空表示无更多数据。")


T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    """通用分页响应。"""

    items: list[T] = Field(description="当前页数据。")
    page: PageInfo = Field(description="分页信息。")


class ErrorResponse(BaseModel):
    """统一错误响应结构。"""

    code: str = Field(description="稳定错误码。")
    message: str = Field(description="面向调用方的错误描述。")
    detail: Any | None = Field(default=None, description="调试细节或字段错误。")
    trace_id: str = Field(description="链路追踪 ID。")


class DecisionRequest(BaseModel):
    """审批、通过或要求修改类动作的请求体。"""

    actor_id: str = Field(default="user", min_length=1, description="操作人或组件标识。")
    reason: str | None = Field(default=None, description="操作原因。")


class EntityRef(BaseModel):
    """事件载荷中常用的实体引用。"""

    id: UUID = Field(description="实体 ID。")
    type: str = Field(description="实体类型。")


class TimeRange(BaseModel):
    """预留时间范围结构，供后续事件过滤扩展使用。"""

    start_at: datetime | None = Field(default=None, description="起始时间。")
    end_at: datetime | None = Field(default=None, description="结束时间。")
