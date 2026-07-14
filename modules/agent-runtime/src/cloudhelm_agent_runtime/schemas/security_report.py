"""Security Agent 输入输出 schema。"""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from cloudhelm_agent_runtime.schemas.agent_io import (
    ArtifactEvidence,
    ChangedFile,
    CommandExecution,
    PlannedToolCommand,
    RiskLevel,
    StrictAgentModel,
    ToolCallEvidence,
)


class SecurityFinding(StrictAgentModel):
    """本地安全扫描发现项。"""

    id: str = Field(pattern=r"^FINDING-[0-9]{3}$")
    scanner: str = Field(min_length=1, max_length=120)
    rule_id: str = Field(min_length=1, max_length=300)
    severity: Literal["info", "low", "medium", "high", "critical"]
    path: str | None = Field(default=None, max_length=500)
    line: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=2000)


class SecurityAgentInput(StrictAgentModel):
    """运行本地扫描命令所需的真实输入。"""

    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    title: str = Field(min_length=1, max_length=300)
    changed_files: list[ChangedFile] = Field(min_length=1)
    scan_commands: list[PlannedToolCommand] = Field(min_length=1)
    accepted_risks: list[str] = Field(default_factory=list)
    execution_recipe_sha256: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    risk_level: RiskLevel


class SecurityAgentOutput(StrictAgentModel):
    """Security Agent 的扫描证据和 PR 阻断结论。"""

    task_id: UUID
    development_plan_id: UUID
    summary: str = Field(min_length=1, max_length=2000)
    verdict: Literal["passed", "failed", "partial", "blocked"]
    scanners: list[CommandExecution] = Field(default_factory=list)
    findings: list[SecurityFinding] = Field(default_factory=list)
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    artifacts: list[ArtifactEvidence] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)
    blocking: bool
    risk_level: RiskLevel

    @field_validator("findings")
    @classmethod
    def ensure_finding_ids(cls, value: list[SecurityFinding]) -> list[SecurityFinding]:
        """发现项 ID 必须唯一且连续。"""

        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("security finding ids must be unique")
        expected = [f"FINDING-{index:03d}" for index in range(1, len(value) + 1)]
        if ids != expected:
            raise ValueError("security finding ids must be consecutive from FINDING-001")
        return value

    @model_validator(mode="after")
    def ensure_verdict_matches_evidence(self) -> "SecurityAgentOutput":
        """阻断结论必须与扫描状态和发现严重级别一致。"""

        severe = any(item.severity in {"high", "critical"} for item in self.findings)
        if self.verdict == "passed" and (
            self.blocking
            or severe
            or self.remaining_risks
            or not self.scanners
            or any(scanner.status != "succeeded" for scanner in self.scanners)
        ):
            raise ValueError("passed security output requires complete successful scans without blocking findings")
        if severe and not self.blocking:
            raise ValueError("high or critical findings must block the PR gate")
        if self.verdict in {"failed", "blocked"} and not self.blocking:
            raise ValueError(f"{self.verdict} security output must be blocking")
        return self
