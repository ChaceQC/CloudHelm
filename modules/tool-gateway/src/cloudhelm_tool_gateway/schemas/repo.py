"""Repo Tool 参数模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class RepoReadFileArguments(BaseModel):
    """读取 workspace 内 UTF-8 文本文件。"""

    workspace_root: str = Field(description="受控 worktree 根目录。")
    path: str = Field(description="相对 workspace 的文件路径。")
    max_bytes: int = Field(default=65536, ge=1, le=262144, description="最多读取字节数。")


class RepoWriteFileArguments(BaseModel):
    """写入 workspace 内 UTF-8 文本文件。"""

    workspace_root: str
    path: str
    content: str = Field(max_length=262144, description="要写入的 UTF-8 文本内容。")
    mode: Literal["replace", "append"] = Field(default="replace", description="写入模式。")
    create_parent: bool = Field(default=False, description="是否创建缺失父目录。")


class RepoSearchTextArguments(BaseModel):
    """在 workspace 内按普通字符串搜索文本。"""

    workspace_root: str
    pattern: str = Field(min_length=1, max_length=200)
    glob: str = Field(default="**/*")
    case_sensitive: bool = Field(default=False)
    max_matches: int = Field(default=50, ge=1, le=200)
    max_file_bytes: int = Field(default=65536, ge=1, le=262144)


class RepoListFilesArguments(BaseModel):
    """列出 workspace 内文件。"""

    workspace_root: str
    path: str = Field(default=".")
    glob: str = Field(default="**/*")
    include_dirs: bool = Field(default=False)
    limit: int = Field(default=100, ge=1, le=500)
