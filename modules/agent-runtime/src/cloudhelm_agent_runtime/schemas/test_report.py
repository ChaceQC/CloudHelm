"""Tester Agent 输入输出 schema。"""

from typing import ClassVar, Literal
from uuid import UUID

from pydantic import Field, model_validator

from cloudhelm_agent_runtime.schemas.agent_io import (
    ArtifactEvidence,
    ChangedFile,
    CommandExecution,
    PlannedToolCommand,
    RiskLevel,
    StrictAgentModel,
    ToolCallEvidence,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion


class AcceptanceTestResult(StrictAgentModel):
    """Tester 对单个验收标准给出的真实测试覆盖结论。"""

    criterion_id: str = Field(
        pattern=r"^AC-(?:[A-Z0-9]+-)*[0-9]{3}$"
    )
    status: Literal["passed", "failed", "not_covered"]
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str = Field(min_length=1, max_length=2000)


class TesterAgentInput(StrictAgentModel):
    """运行真实测试命令所需的结构化输入。"""

    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    title: str = Field(min_length=1, max_length=300)
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    changed_files: list[ChangedFile] = Field(min_length=1)
    commands: list[PlannedToolCommand] = Field(min_length=1)
    execution_recipe_sha256: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    risk_level: RiskLevel


class TesterAgentOutput(StrictAgentModel):
    """Tester Agent 的真实测试报告。"""

    __test__: ClassVar[bool] = False

    task_id: UUID
    development_plan_id: UUID
    summary: str = Field(min_length=1, max_length=2000)
    status: Literal["passed", "failed", "partial", "blocked"]
    commands: list[CommandExecution] = Field(default_factory=list)
    passed_count: int | None = Field(default=None, ge=0)
    failed_count: int | None = Field(default=None, ge=0)
    skipped_count: int | None = Field(default=None, ge=0)
    acceptance_results: list[AcceptanceTestResult] = Field(min_length=1)
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    artifacts: list[ArtifactEvidence] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    risk_level: RiskLevel

    @model_validator(mode="after")
    def ensure_status_matches_evidence(self) -> "TesterAgentOutput":
        """测试通过必须由命令退出码和失败数共同证明。"""

        ids = [item.criterion_id for item in self.acceptance_results]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance test result ids must be unique")
        if self.status == "passed":
            if not self.commands:
                raise ValueError("passed test output requires command evidence")
            if any(command.status != "succeeded" or command.exit_code not in {0, None} for command in self.commands):
                raise ValueError("passed test output cannot contain failed commands")
            if self.failed_count not in {0, None}:
                raise ValueError("passed test output requires failed_count=0")
            if self.failure_reasons:
                raise ValueError("passed test output cannot contain failure reasons")
            if any(
                item.status != "passed"
                for item in self.acceptance_results
            ):
                raise ValueError(
                    "passed test output requires every acceptance result passed"
                )
        if self.status in {"failed", "blocked"} and not self.failure_reasons:
            raise ValueError(f"{self.status} test output requires failure reasons")
        if self.status == "failed" and not any(
            item.status == "failed" for item in self.acceptance_results
        ):
            raise ValueError(
                "failed test output requires a failed acceptance result"
            )
        if self.status == "blocked" and any(
            item.status != "not_covered"
            for item in self.acceptance_results
        ):
            raise ValueError(
                "blocked test output requires not_covered acceptance results"
            )
        return self
