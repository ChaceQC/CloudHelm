"""Planner Agent 与 Development Plan schema。"""

from uuid import UUID

from typing import Literal

from pydantic import Field, field_validator

from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel, StrictAgentModel


class DevelopmentPlanStep(StrictAgentModel):
    """开发计划步骤。

    M4 只生成任务图，不执行代码、工具或 Git 操作。
    """

    id: str = Field(pattern=r"^STEP-[0-9]{3}$", description="步骤编号。")
    title: str = Field(min_length=1, description="步骤标题。")
    description: str = Field(min_length=1, description="步骤说明。")
    agent: Literal[
        "requirement",
        "architect",
        "planner",
        "scaffold",
        "coder",
        "tester",
        "reviewer",
        "security",
        "release",
        "deploy",
        "sre",
    ] = Field(description="建议负责的后续 Agent。")
    expected_artifact: str = Field(min_length=1, description="预期产物。")
    depends_on: list[str] = Field(default_factory=list, description="依赖的步骤编号。")
    execution_recipe: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$",
        description="M6 受控本地 execution recipe ID。",
    )
    status: Literal["pending"] = Field(default="pending", description="M4 仅生成 pending 状态。")


class DevelopmentPlanRisk(StrictAgentModel):
    """开发计划风险项。"""

    id: str = Field(pattern=r"^RISK-[0-9]{3}$", description="风险编号。")
    description: str = Field(min_length=1, description="风险描述。")
    mitigation: str = Field(min_length=1, description="缓解措施。")
    risk_level: RiskLevel = Field(description="风险等级。")


class PlannerAgentInput(StrictAgentModel):
    """Planner Agent 输入。"""

    task_id: UUID = Field(description="任务 ID。")
    project_id: UUID = Field(description="项目 ID。")
    technical_design_id: UUID = Field(description="关联技术设计 ID。")
    title: str = Field(min_length=1, description="任务标题。")
    design_summary: str = Field(min_length=1, description="设计摘要或正文。")
    risk_level: RiskLevel = Field(description="技术设计风险等级。")


class PlannerAgentOutput(StrictAgentModel):
    """Planner Agent 输出。

    输出映射到 `development_plans`，作为 M5 工具层前的可审查计划。
    """

    summary: str = Field(min_length=1, description="开发计划摘要。")
    steps: list[DevelopmentPlanStep] = Field(min_length=1, description="任务图步骤。")
    risks: list[DevelopmentPlanRisk] = Field(default_factory=list, description="计划风险。")
    status: Literal["ready_for_review"] = Field(default="ready_for_review", description="计划状态。")
    risk_level: RiskLevel = Field(description="计划最高风险。")

    @field_validator("steps")
    @classmethod
    def ensure_step_dependencies_exist(cls, steps: list[DevelopmentPlanStep]) -> list[DevelopmentPlanStep]:
        """校验步骤依赖引用真实存在，避免后续编排读到断裂任务图。"""

        ordered_ids = [step.id for step in steps]
        if len(ordered_ids) != len(set(ordered_ids)):
            raise ValueError("development plan step ids must be unique")
        expected = [f"STEP-{index:03d}" for index in range(1, len(steps) + 1)]
        if ordered_ids != expected:
            raise ValueError("development plan step ids must be consecutive from STEP-001")
        ids = set(ordered_ids)
        missing = sorted({dep for step in steps for dep in step.depends_on if dep not in ids})
        if missing:
            raise ValueError(f"unknown step dependencies: {', '.join(missing)}")
        if any(step.id in step.depends_on for step in steps):
            raise ValueError("development plan steps cannot depend on themselves")

        graph = {step.id: set(step.depends_on) for step in steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("development plan step dependencies must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in graph[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ordered_ids:
            visit(step_id)
        return steps
