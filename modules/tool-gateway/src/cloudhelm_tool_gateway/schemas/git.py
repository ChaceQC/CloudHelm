"""Git Tool 参数模型。"""

from pydantic import BaseModel, Field


class GitStatusArguments(BaseModel):
    """读取受控 Git 仓库状态。"""

    repo_root: str
    porcelain: bool = Field(default=True)


class GitDiffArguments(BaseModel):
    """读取受控 Git 仓库 diff。"""

    repo_root: str
    paths: list[str] = Field(default_factory=list)
    context_lines: int = Field(default=3, ge=0, le=20)
    max_output_chars: int = Field(default=12000, ge=100, le=50000)


class GitCreateBranchArguments(BaseModel):
    """创建并切换本地开发分支。"""

    repo_root: str
    branch_name: str = Field(min_length=1, max_length=80)


class GitCommitArguments(BaseModel):
    """提交显式文件列表到本地 Git 仓库。"""

    repo_root: str
    message: str = Field(min_length=3, max_length=200)
    paths: list[str] = Field(min_length=1)
