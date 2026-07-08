"""DevelopmentPlan API DTO。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from cloudhelm_platform_api.schemas.common import DevelopmentPlanStatus, OrmModel


class DevelopmentPlanCreate(BaseModel):
    """创建 DevelopmentPlan 的内部 DTO。

    外部调用方不直接创建计划；M4 由 Planner Agent 通过 Orchestrator 写入。
    """

    technical_design_id: UUID = Field(description="关联技术设计 ID。")
    summary: str = Field(min_length=1, description="开发计划摘要。")
    steps_json: list[dict[str, Any]] = Field(min_length=1, description="任务图步骤 JSON。")
    risks_json: list[dict[str, Any]] = Field(default_factory=list, description="计划风险 JSON。")
    status: DevelopmentPlanStatus = Field(default=DevelopmentPlanStatus.READY_FOR_REVIEW, description="计划状态。")
    created_by_agent_run_id: UUID | None = Field(default=None, description="创建计划的 Planner AgentRun。")

    @field_validator("steps_json")
    @classmethod
    def ensure_steps_have_ids(cls, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """校验步骤至少包含稳定 id，便于后续 M5/M6 追溯。"""

        for step in steps:
            if not step.get("id"):
                raise ValueError("each development plan step must have id")
        return steps


class DevelopmentPlanRead(OrmModel):
    """DevelopmentPlan 响应结构。"""

    id: UUID
    task_id: UUID
    project_id: UUID
    technical_design_id: UUID
    summary: str
    steps_json: list[dict[str, Any]]
    risks_json: list[dict[str, Any]]
    status: DevelopmentPlanStatus
    version: int
    created_by_agent_run_id: UUID | None
    created_at: datetime
    updated_at: datetime
