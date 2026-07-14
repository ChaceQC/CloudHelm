"""Agent 输入输出的通用类型。

这些类型不依赖 Platform API ORM，便于 agent-runtime 在独立测试环境中
验证结构化输出，同时让 Platform API 以 DTO 方式消费校验后的对象。
所有 Agent schema 默认拒绝额外字段，避免稳定传输 schema 的宽松字段集合
绕过当前角色的专属业务契约。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskLevel(str, Enum):
    """CloudHelm M4 复用的风险等级。

    L0/L1 可在 M4 内自动推进；L2 及以上需要进入设计审批或后续工具审批。
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


def max_risk_level(*levels: RiskLevel) -> RiskLevel:
    """返回输入风险中的最高等级，避免跨 Agent 传递时发生风险降级。"""

    if not levels:
        raise ValueError("at least one risk level is required")
    order = {level: index for index, level in enumerate(RiskLevel)}
    return max(levels, key=order.__getitem__)


class StrictAgentModel(BaseModel):
    """Agent Runtime schema 的严格基类。"""

    model_config = ConfigDict(extra="forbid")


class ToolCallEvidence(StrictAgentModel):
    """最终 Agent 输出引用的一次真实工具调用。"""

    call_id: str = Field(min_length=1, max_length=200, description="模型 function/custom call ID。")
    tool_name: str = Field(min_length=1, max_length=120, description="Tool Gateway 工具名。")
    status: Literal["succeeded", "failed", "waiting_approval"] = Field(description="真实工具终态。")
    tool_call_id: str | None = Field(default=None, description="Platform API 持久化 ToolCall ID。")
    error_code: str | None = Field(default=None, description="失败错误码。")
    summary: str = Field(min_length=1, max_length=1000, description="已脱敏执行摘要。")


class ArtifactEvidence(StrictAgentModel):
    """Agent 输出引用的受控 Artifact。"""

    type: str = Field(min_length=1, max_length=80, description="Artifact 类型。")
    ref: str = Field(min_length=1, max_length=500, description="受控 URI 或相对引用。")
    sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="真实产物 SHA-256；没有工具证据时保持为空。",
    )
    size_bytes: int | None = Field(default=None, ge=0, description="真实产物大小。")


class PlannedFileWrite(StrictAgentModel):
    """Scaffold/Coder 输入中的显式文件写入计划。"""

    path: str = Field(min_length=1, max_length=500, description="受控 workspace 内相对路径。")
    operation: Literal["create", "update"] = Field(description="预期文件操作。")
    purpose: str = Field(min_length=1, max_length=1000, description="本文件修改意图。")
    content: str = Field(description="待写入的完整 UTF-8 文本。")
    create_parent: bool = Field(default=False, description="是否创建缺失父目录。")

    @field_validator("path")
    @classmethod
    def ensure_relative_path(cls, value: str) -> str:
        """拒绝绝对路径和父目录跳转，真实根目录由 Platform API 绑定。"""

        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("file path must stay relative to the bound workspace")
        return normalized


class PlannedCommand(StrictAgentModel):
    """Tester/Security/Coder 输入中的显式非交互命令计划。"""

    command: list[str] = Field(min_length=1, description="不经过 shell 拼接的命令数组。")
    purpose: str = Field(min_length=1, max_length=1000, description="命令用途和期望证据。")
    cwd: str = Field(default=".", min_length=1, max_length=500, description="受控 workspace 内相对目录。")
    timeout_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("command")
    @classmethod
    def ensure_command_parts(cls, value: list[str]) -> list[str]:
        """拒绝空参数；程序与参数权限继续由 Tool Gateway 判断。"""

        if any(not part.strip() for part in value):
            raise ValueError("command items cannot be empty")
        return value

    @field_validator("cwd")
    @classmethod
    def ensure_relative_cwd(cls, value: str) -> str:
        """命令目录只能是受控 workspace 内相对路径。"""

        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("command cwd must stay relative to the bound workspace")
        return normalized


class PlannedToolCommand(StrictAgentModel):
    """Tester/Security 输入中的领域 Tool Gateway 调用计划。"""

    tool_name: Literal[
        "test.run_pytest",
        "security.run_bandit",
        "security.run_pip_audit",
    ]
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="模型可见工具参数；workspace_root 由 Platform API 绑定。",
    )
    command: list[str] = Field(
        min_length=1,
        description="控制台和报告展示的等价命令数组。",
    )
    purpose: str = Field(min_length=1, max_length=1000)

    @field_validator("command")
    @classmethod
    def ensure_display_command(cls, value: list[str]) -> list[str]:
        """展示命令同样拒绝空参数。"""

        return PlannedCommand.ensure_command_parts(value)


class ChangedFile(StrictAgentModel):
    """Scaffold/Coder 输出中的真实文件变更引用。"""

    path: str = Field(min_length=1, max_length=500)
    operation: Literal["created", "updated", "deleted"]
    intent: str = Field(min_length=1, max_length=1000)
    tool_call_id: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def ensure_relative_path(cls, value: str) -> str:
        """沿用工具层的相对路径边界。"""

        return PlannedFileWrite.ensure_relative_path(value)


class CommandExecution(StrictAgentModel):
    """Tester/Coder/Security 输出中的真实命令执行证据。"""

    call_id: str = Field(min_length=1, max_length=200)
    tool_call_id: str | None = None
    command: list[str] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=1000)
    status: Literal["succeeded", "failed", "waiting_approval"]
    exit_code: int | None = None
    passed_count: int | None = Field(default=None, ge=0)
    failed_count: int | None = Field(default=None, ge=0)
    skipped_count: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    report_ref: str | None = Field(default=None, max_length=500)
    stdout_summary: str | None = Field(default=None, max_length=4000)
    stderr_summary: str | None = Field(default=None, max_length=4000)
    error_code: str | None = Field(default=None, max_length=120)


class AgentExecutionMetadata(StrictAgentModel):
    """Agent 输出随附的审计元数据。

    Provider 只负责模型或规则化生成，不写数据库；该元数据由调用方写入
    `agent_runs`，用于追踪模型、prompt 版本和结构化输出类型。
    """

    provider: str = Field(description="生成输出的 provider 名称。")
    model_name: str | None = Field(default=None, description="外部模型名；本地 provider 可为空。")
    prompt_version: str = Field(default="m4-v1", description="Prompt 或规则版本。")
    generated_at: datetime | None = Field(default=None, description="生成时间；调用方可按需补齐。")
