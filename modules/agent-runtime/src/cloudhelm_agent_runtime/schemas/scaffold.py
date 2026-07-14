"""Scaffold Agent 输入输出 schema。"""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

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


class ScaffoldAgentInput(StrictAgentModel):
    """根据已批准计划生成项目或模块骨架的显式输入。"""

    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    step_id: str = Field(pattern=r"^STEP-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=300)
    workspace_ref: str = Field(min_length=1, max_length=300)
    template_id: Literal["sample-repo-python"] = "sample-repo-python"
    baseline_branch: str = Field(
        default="main",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$",
    )
    execution_recipe_sha256: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    planned_files: list[PlannedFileWrite] = Field(
        default_factory=list,
        description="上游已批准的完整文件写入计划；Local Provider 不自行编造文件。",
    )
    verification_commands: list[PlannedCommand] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    risk_level: RiskLevel


class ScaffoldAgentOutput(StrictAgentModel):
    """Scaffold Agent 的真实文件与验证结果。"""

    task_id: UUID
    development_plan_id: UUID
    step_id: str = Field(pattern=r"^STEP-[0-9]{3}$")
    summary: str = Field(min_length=1, max_length=2000)
    status: Literal["completed", "partial", "blocked"]
    workspace_key: str | None = Field(default=None, max_length=500)
    baseline_branch: str | None = Field(default=None, max_length=120)
    baseline_commit: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$",
    )
    baseline_files: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    verification: list[CommandExecution] = Field(default_factory=list)
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    artifacts: list[ArtifactEvidence] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    risk_level: RiskLevel

    @model_validator(mode="after")
    def ensure_status_matches_evidence(self) -> "ScaffoldAgentOutput":
        """完成状态必须拥有真实写入证据；阻塞状态必须说明原因。"""

        if self.status == "completed" and (
            not self.workspace_key
            or not self.baseline_commit
            or not self.tool_calls
            or self.blockers
        ):
            raise ValueError(
                "completed scaffold output requires workspace evidence and no blockers"
            )
        if self.status == "blocked" and not self.blockers:
            raise ValueError("blocked scaffold output requires blockers")
        return self
