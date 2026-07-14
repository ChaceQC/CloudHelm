"""M6 受控 sample repo execution recipe schema。

Recipe 是 DevelopmentPlan 引用的版本化执行输入，不是运行结果。它只描述
完整 UTF-8 文件计划、受控命令 profile 和 AC 映射；所有文件、测试、安全与
Git 副作用仍必须经过 Agent Runtime 与 Tool Gateway。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cloudhelm_agent_runtime.schemas.agent_io import PlannedCommand, PlannedFileWrite


class RecipeTestCommand(BaseModel):
    """Tester 使用的 pytest 领域工具调用计划。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal["test.run_pytest"]
    purpose: str = Field(min_length=1, max_length=1000)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RecipeSecurityCommand(BaseModel):
    """Security 使用的本地扫描工具调用计划。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: Literal[
        "security.run_bandit",
        "security.run_pip_audit",
    ]
    purpose: str = Field(min_length=1, max_length=1000)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RecipeAcceptanceEvidence(BaseModel):
    """一个已批准 AC 与真实测试证据的映射说明。"""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^AC-(?:[A-Z0-9]+-)*[0-9]{3}$",
    )
    notes: str = Field(min_length=1, max_length=2000)


class LocalExecutionRecipe(BaseModel):
    """M6 sample fixture 的完整、可审计执行输入。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    recipe_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    template_id: Literal["sample-repo-python"]
    issue_path: str = Field(min_length=1, max_length=300)
    implementation_goal: str = Field(min_length=1, max_length=4000)
    step_ids: list[str] = Field(min_length=1)
    planned_changes: list[PlannedFileWrite] = Field(min_length=1)
    coder_verification_commands: list[PlannedCommand] = Field(
        default_factory=list
    )
    test_commands: list[RecipeTestCommand] = Field(min_length=1)
    security_commands: list[RecipeSecurityCommand] = Field(min_length=1)
    acceptance_evidence: list[RecipeAcceptanceEvidence] = Field(min_length=1)

    @field_validator("step_ids")
    @classmethod
    def validate_step_ids(cls, value: list[str]) -> list[str]:
        """步骤 ID 必须唯一并使用 DevelopmentPlan 稳定格式。"""

        if len(value) != len(set(value)):
            raise ValueError("recipe step ids must be unique")
        if any(
            len(step_id) != 8
            or not step_id.startswith("STEP-")
            or not step_id[5:].isdigit()
            for step_id in value
        ):
            raise ValueError("recipe step ids must match STEP-000")
        return value

    @field_validator("issue_path")
    @classmethod
    def validate_issue_path(cls, value: str) -> str:
        """Issue 引用必须位于 fixture 的 demo-issues 目录。"""

        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) != 2
            or path.parts[0] != "demo-issues"
            or path.suffix.lower() != ".md"
        ):
            raise ValueError(
                "issue_path must be demo-issues/<name>.md"
            )
        return path.as_posix()

    @field_validator("acceptance_evidence")
    @classmethod
    def validate_acceptance_ids(
        cls,
        value: list[RecipeAcceptanceEvidence],
    ) -> list[RecipeAcceptanceEvidence]:
        """同一 AC 只能映射一次。"""

        ids = [item.criterion_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("recipe acceptance ids must be unique")
        return value
