"""本地安全扫描工具参数模型。"""

from pydantic import BaseModel, ConfigDict, Field


class SecurityRunBanditArguments(BaseModel):
    """执行 Bandit 递归 Python SAST。"""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str = Field(description="服务端绑定的 Task workspace。")
    cwd: str = Field(default=".")
    path: str = Field(default="src", min_length=1, max_length=240)
    timeout_seconds: int = Field(default=180, ge=1, le=300)
    max_output_chars: int = Field(default=12000, ge=200, le=50000)


class SecurityRunPipAuditArguments(BaseModel):
    """执行 pip-audit 依赖漏洞扫描。"""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str = Field(description="服务端绑定的 Task workspace。")
    cwd: str = Field(default=".")
    timeout_seconds: int = Field(default=240, ge=1, le=300)
    max_output_chars: int = Field(default=12000, ge=200, le=50000)
