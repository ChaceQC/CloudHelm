"""Git Tool 参数模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitStatusArguments(BaseModel):
    """读取受控 Git 仓库状态。"""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    porcelain: bool = Field(default=True)


class GitDiffArguments(BaseModel):
    """读取受控 Git 仓库 diff。"""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    paths: list[str] = Field(default_factory=list)
    from_ref: str | None = Field(default=None, max_length=120)
    to_ref: str | None = Field(default=None, max_length=120)
    include_untracked: bool = Field(default=True)
    context_lines: int = Field(default=3, ge=0, le=20)
    max_output_chars: int = Field(default=50000, ge=100, le=200000)

    @field_validator("from_ref", "to_ref")
    @classmethod
    def validate_ref(cls, value: str | None) -> str | None:
        """拒绝以选项形式解释的 rev，并限制常见安全字符。"""

        if value is None:
            return None
        if value.startswith("-") or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-~^" for char in value):
            raise ValueError("invalid git ref")
        return value


class GitCreateBranchArguments(BaseModel):
    """创建并切换本地开发分支。"""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    branch_name: str = Field(min_length=1, max_length=80)


class GitCommitArguments(BaseModel):
    """提交显式文件列表到本地 Git 仓库。"""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    message: str = Field(min_length=3, max_length=200)
    paths: list[str] = Field(min_length=1)


class GitFormatPatchArguments(BaseModel):
    """生成 base/head 间的邮件格式 patch。"""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    base_ref: str = Field(default="main", min_length=1, max_length=120)
    head_ref: str = Field(default="HEAD", min_length=1, max_length=120)
    max_output_chars: int = Field(default=200000, ge=1000, le=1000000)

    @field_validator("base_ref", "head_ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        """限制 patch ref，防止把 rev 解释为 Git 选项。"""

        if value.startswith("-") or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-~^" for char in value):
            raise ValueError("invalid git ref")
        return value
