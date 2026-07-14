"""Reviewer Agent 输入输出 schema。"""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from cloudhelm_agent_runtime.schemas.agent_io import (
    ChangedFile,
    RiskLevel,
    StrictAgentModel,
    ToolCallEvidence,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentOutput


class AcceptanceReview(StrictAgentModel):
    """一个验收标准的评审结论与证据。"""

    criterion_id: str = Field(
        pattern=r"^AC-(?:[A-Z0-9]+-)*[0-9]{3}$"
    )
    status: Literal["satisfied", "partial", "missing"]
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str = Field(min_length=1, max_length=2000)


class ReviewIssue(StrictAgentModel):
    """Reviewer 发现的可追溯问题。"""

    id: str = Field(pattern=r"^ISSUE-[0-9]{3}$")
    severity: Literal["low", "medium", "high", "critical"]
    path: str | None = Field(default=None, max_length=500)
    line: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=2000)
    recommendation: str = Field(min_length=1, max_length=2000)


class ReviewerAgentInput(StrictAgentModel):
    """基于真实 diff、AC 和测试报告执行评审。"""

    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    title: str = Field(min_length=1, max_length=300)
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    acceptance_evidence: list[AcceptanceReview] = Field(min_length=1)
    changed_files: list[ChangedFile] = Field(min_length=1)
    diff_paths: list[str] = Field(default_factory=list)
    test_report: TesterAgentOutput
    known_issues: list[ReviewIssue] = Field(default_factory=list)
    execution_recipe_sha256: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    risk_level: RiskLevel

    @field_validator("acceptance_evidence")
    @classmethod
    def ensure_acceptance_ids_unique(cls, value: list[AcceptanceReview]) -> list[AcceptanceReview]:
        """每个 AC 只能出现一次评审证据。"""

        ids = [item.criterion_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance review criterion ids must be unique")
        return value


class ReviewerAgentOutput(StrictAgentModel):
    """Reviewer Agent 的验收映射与代码审查结论。"""

    task_id: UUID
    development_plan_id: UUID
    summary: str = Field(min_length=1, max_length=2000)
    verdict: Literal["approved", "changes_requested", "blocked"]
    acceptance_results: list[AcceptanceReview] = Field(min_length=1)
    issues: list[ReviewIssue] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(min_length=1)
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    proceed_to_security: bool
    risk_level: RiskLevel

    @model_validator(mode="after")
    def ensure_verdict_matches_evidence(self) -> "ReviewerAgentOutput":
        """批准结论必须满足全部 AC、测试通过且没有问题。"""

        if self.verdict == "approved":
            if any(item.status != "satisfied" for item in self.acceptance_results):
                raise ValueError("approved review requires every acceptance criterion satisfied")
            if self.issues or not self.proceed_to_security:
                raise ValueError("approved review cannot contain issues and must proceed to security")
        if self.verdict != "approved" and self.proceed_to_security:
            raise ValueError("non-approved review cannot proceed to security")
        return self
