"""Planner Agent 与 Development Plan schema。"""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel


class DevelopmentPlanStep(BaseModel):
    """开发计划步骤。

    M4 只生成任务图，不执行代码、工具或 Git 操作。
    """

    id: str = Field(pattern=r"^STEP-[0-9]{3}$", description="步骤编号。")
    title: str = Field(min_length=1, description="步骤标题。")
    description: str = Field(min_length=1, description="步骤说明。")
    agent: str = Field(min_length=1, description="建议负责的后续 Agent。")
    expected_artifact: str = Field(min_length=1, description="预期产物。")
    depends_on: list[str] = Field(default_factory=list, description="依赖的步骤编号。")
    status: str = Field(default="pending", description="M4 仅生成 pending 状态。")


class DevelopmentPlanRisk(BaseModel):
    """开发计划风险项。"""

    id: str = Field(pattern=r"^RISK-[0-9]{3}$", description="风险编号。")
    description: str = Field(min_length=1, description="风险描述。")
    mitigation: str = Field(min_length=1, description="缓解措施。")
    risk_level: RiskLevel = Field(description="风险等级。")


class PlannerAgentInput(BaseModel):
    """Planner Agent 输入。"""

    task_id: UUID = Field(description="任务 ID。")
    project_id: UUID = Field(description="项目 ID。")
    technical_design_id: UUID = Field(description="关联技术设计 ID。")
    title: str = Field(min_length=1, description="任务标题。")
    design_summary: str = Field(min_length=1, description="设计摘要或正文。")
    risk_level: RiskLevel = Field(description="技术设计风险等级。")


class PlannerAgentOutput(BaseModel):
    """Planner Agent 输出。

    输出映射到 `development_plans`，作为 M5 工具层前的可审查计划。
    """

    summary: str = Field(min_length=1, description="开发计划摘要。")
    steps: list[DevelopmentPlanStep] = Field(min_length=1, description="任务图步骤。")
    risks: list[DevelopmentPlanRisk] = Field(default_factory=list, description="计划风险。")
    status: str = Field(default="ready_for_review", description="计划状态。")
    risk_level: RiskLevel = Field(description="计划最高风险。")

    @field_validator("steps")
    @classmethod
    def ensure_step_dependencies_exist(cls, steps: list[DevelopmentPlanStep]) -> list[DevelopmentPlanStep]:
        """校验步骤依赖引用真实存在，避免后续编排读到断裂任务图。"""

        ids = {step.id for step in steps}
        missing = sorted({dep for step in steps for dep in step.depends_on if dep not in ids})
        if missing:
            raise ValueError(f"unknown step dependencies: {', '.join(missing)}")
        return steps
