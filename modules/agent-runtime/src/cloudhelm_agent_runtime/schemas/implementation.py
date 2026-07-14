"""Coder Agent 输入输出 schema。"""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from cloudhelm_agent_runtime.schemas.agent_io import (
    ArtifactEvidence,
    ChangedFile,
    CommandExecution,
    PlannedCommand,
    PlannedFileWrite,
    RiskLevel,
    StrictAgentModel,
    ToolCallEvidence,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion


class CoderAgentInput(StrictAgentModel):
    """基于已批准 DevelopmentPlan 执行显式代码变更。"""

    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    step_ids: list[str] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    implementation_goal: str = Field(min_length=1, max_length=4000)
    branch_name: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$",
    )
    execution_recipe_sha256: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    planned_changes: list[PlannedFileWrite] = Field(
        min_length=1,
        description="包含真实 UTF-8 内容的已批准写入计划。",
    )
    verification_commands: list[PlannedCommand] = Field(default_factory=list)
    prior_feedback: list[str] = Field(default_factory=list)
    risk_level: RiskLevel

    @field_validator("step_ids")
    @classmethod
    def ensure_step_ids(cls, value: list[str]) -> list[str]:
        """步骤引用必须唯一且符合 DevelopmentPlan 编号格式。"""

        if len(value) != len(set(value)):
            raise ValueError("coder step ids must be unique")
        if any(not step.startswith("STEP-") or len(step) != 8 or not step[5:].isdigit() for step in value):
            raise ValueError("coder step ids must match STEP-000")
        return value


class CoderAgentOutput(StrictAgentModel):
    """Coder Agent 的真实实现结果。"""

    task_id: UUID
    development_plan_id: UUID
    step_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=2000)
    status: Literal["completed", "partial", "blocked"]
    branch_name: str | None = Field(default=None, max_length=80)
    diff_paths: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    verification: list[CommandExecution] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    artifacts: list[ArtifactEvidence] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    risk_level: RiskLevel

    @model_validator(mode="after")
    def ensure_status_matches_evidence(self) -> "CoderAgentOutput":
        """完成状态必须有真实文件写入且不得包含失败工具。"""

        failed = [call for call in self.tool_calls if call.status != "succeeded"]
        if self.status == "completed" and (
            not self.changed_files
            or not self.branch_name
            or not self.diff_paths
            or failed
            or self.blockers
        ):
            raise ValueError(
                "completed coder output requires branch, diff, file changes and no blockers"
            )
        if self.status == "blocked" and not self.blockers:
            raise ValueError("blocked coder output requires blockers")
        return self
