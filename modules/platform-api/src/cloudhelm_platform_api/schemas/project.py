"""Project API DTO。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import OrmModel


class ProjectCreate(BaseModel):
    """创建 Project 的请求体。"""

    name: str = Field(min_length=1, max_length=120, description="项目显示名称。")
    repo_url: str = Field(min_length=1, description="仓库地址或本地仓库路径。")
    default_branch: str = Field(default="main", min_length=1, description="默认分支。")
    provider: str = Field(default="git", min_length=1, description="仓库提供方。")


class ProjectRead(OrmModel):
    """Project 响应结构。"""

    id: UUID
    name: str
    repo_url: str
    default_branch: str
    provider: str
    created_at: datetime
    updated_at: datetime
