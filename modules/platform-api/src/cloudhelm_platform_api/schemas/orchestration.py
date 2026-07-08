"""M4 Orchestration API DTO。"""

from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.agent_run import AgentRunRead
from cloudhelm_platform_api.schemas.approval import ApprovalRequestRead
from cloudhelm_platform_api.schemas.design import TechnicalDesignRead
from cloudhelm_platform_api.schemas.development_plan import DevelopmentPlanRead
from cloudhelm_platform_api.schemas.requirement import RequirementSpecRead
from cloudhelm_platform_api.schemas.task import TaskRead


class OrchestrationActionRequest(BaseModel):
    """启动或推进编排的请求体。"""

    actor_id: str = Field(default="control-console", min_length=1, description="操作人或调用组件。")
    reason: str | None = Field(default=None, description="用户或系统给出的推进原因。")


class OrchestrationStepRead(BaseModel):
    """一次 M4 编排推进结果。"""

    task: TaskRead = Field(description="推进后的任务状态。")
    action: str = Field(description="实际执行或等待的动作。")
    message: str = Field(description="面向控制台的说明。")
    agent_run: AgentRunRead | None = Field(default=None, description="本次生成的 AgentRun。")
    requirement: RequirementSpecRead | None = Field(default=None, description="本次生成的 RequirementSpec。")
    technical_design: TechnicalDesignRead | None = Field(default=None, description="本次生成的 TechnicalDesign。")
    development_plan: DevelopmentPlanRead | None = Field(default=None, description="本次生成的 DevelopmentPlan。")
    approval: ApprovalRequestRead | None = Field(default=None, description="本次创建或等待的审批。")


class OrchestrationStateRead(BaseModel):
    """任务当前 M4 编排状态摘要。"""

    task_id: UUID = Field(description="任务 ID。")
    current_phase: str = Field(description="当前阶段。")
    next_action: str = Field(description="下一步可执行动作。")
    plan_exists: bool = Field(description="是否已有 DevelopmentPlan。")
    design_approved: bool = Field(description="是否已有通过的设计。")
