"""Scaffold Tool 参数模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScaffoldPrepareWorkspaceArguments(BaseModel):
    """从受控 fixture 准备 Task 独立 Git workspace。"""

    model_config = ConfigDict(extra="forbid")

    template_id: Literal["sample-repo-python"] = Field(
        default="sample-repo-python",
        description="服务端已登记的模板标识。",
    )
    source_root: str = Field(description="服务端绑定的 fixture 根目录。")
    workspace_root: str = Field(description="服务端绑定的 M6 workspace 父目录。")
    target_directory: str = Field(description="服务端按 Task 生成的相对目标目录。")
    baseline_branch: str = Field(default="main", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")
    git_user_name: str = Field(default="CloudHelm Agent", min_length=1, max_length=120)
    git_user_email: str = Field(default="cloudhelm@example.invalid", min_length=3, max_length=200)
