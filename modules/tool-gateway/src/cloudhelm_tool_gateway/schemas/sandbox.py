"""Sandbox Tool 参数模型。"""

from pydantic import BaseModel, ConfigDict, Field


class SandboxRunCommandArguments(BaseModel):
    """在本地受控目录执行非交互式命令。"""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str = Field(description="受控 sandbox 根目录。")
    cwd: str = Field(default=".", description="相对 sandbox 根目录的执行目录。")
    command: list[str] = Field(min_length=1, description="命令数组，不通过 shell 拼接。")
    timeout_seconds: int = Field(default=10, ge=1, le=300)
    env: dict[str, str] = Field(default_factory=dict, description="白名单环境变量覆盖。")
    max_output_chars: int = Field(default=4000, ge=100, le=12000)


class SandboxCollectArtifactArguments(BaseModel):
    """收集 sandbox 内产物元数据。"""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str
    path: str
    max_bytes: int = Field(default=1048576, ge=1, le=5242880)
