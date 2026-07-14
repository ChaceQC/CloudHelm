"""Requirement Agent 输入输出 schema。"""

from uuid import UUID

from typing import Literal

from pydantic import Field, field_validator

from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel, StrictAgentModel


class RequirementConstraint(StrictAgentModel):
    """需求约束项。

    约束必须说明类型、内容和是否硬性要求，避免后续 Architect / Planner
    只能依赖自然语言猜测边界。
    """

    type: str = Field(min_length=1, description="约束类型，例如 technology、security、testing。")
    value: str = Field(min_length=1, description="约束内容。")
    required: bool = Field(default=True, description="是否为必须满足的硬约束。")


class AcceptanceCriterion(StrictAgentModel):
    """验收标准项。"""

    id: str = Field(
        pattern=r"^AC-(?:[A-Z0-9]+-)*[0-9]{3}$",
        description="稳定验收标准编号，可保留领域前缀。",
    )
    description: str = Field(min_length=1, description="从用户视角可验证的验收描述。")
    verification: str = Field(min_length=1, description="建议验证方式，例如 pytest、API、manual。")
    status: Literal["pending"] = Field(default="pending", description="验收状态，M4 仅生成 pending。")


class RequirementAgentInput(StrictAgentModel):
    """Requirement Agent 输入。

    输入必须来自真实 Task，不允许使用测试夹具或固定样例冒充需求来源。
    """

    task_id: UUID = Field(description="任务 ID。")
    project_id: UUID = Field(description="项目 ID。")
    title: str = Field(min_length=1, description="任务标题。")
    description: str = Field(min_length=1, description="任务描述。")
    source_type: str = Field(min_length=1, description="任务来源类型。")
    source_ref: str | None = Field(default=None, description="任务来源引用。")
    risk_level: RiskLevel = Field(description="任务初始风险等级。")


class RequirementAgentOutput(StrictAgentModel):
    """Requirement Agent 输出。

    Platform API 会把该对象映射到 `requirement_specs`，其中 JSON 数组字段
    直接由 `constraints` 和 `acceptance_criteria` 序列化得到。
    """

    summary: str = Field(min_length=1, description="需求规格摘要。")
    raw_input: str = Field(min_length=1, description="保留的原始输入。")
    user_story: str = Field(min_length=1, description="用户故事。")
    constraints: list[RequirementConstraint] = Field(min_length=1, description="约束条件。")
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1, description="验收标准。")
    risk_level: RiskLevel = Field(description="需求阶段识别出的最高风险。")

    @field_validator("acceptance_criteria")
    @classmethod
    def ensure_unique_acceptance_ids(cls, criteria: list[AcceptanceCriterion]) -> list[AcceptanceCriterion]:
        """确保验收标准编号唯一，避免控制台和后续测试追溯混乱。"""

        ids = [item.id for item in criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance criterion ids must be unique")
        return criteria
