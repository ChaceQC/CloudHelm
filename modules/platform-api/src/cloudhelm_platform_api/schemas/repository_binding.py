"""M7 ProjectRepositoryBinding API DTO。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cloudhelm_platform_api.schemas.common import OrmModel


class RepositoryBindingPut(BaseModel):
    """普通调用方只能选择服务端 repository profile。"""

    model_config = ConfigDict(extra="forbid")

    profile_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
        description="服务端 RepositoryProfile key。",
    )


class RepositoryBindingRead(OrmModel):
    """不暴露 clone URL 或 credential 引用的仓库绑定响应。"""

    id: UUID
    project_id: UUID
    provider: Literal["gitea"]
    profile_key: str
    repository_external_id: str
    repository_owner: str
    repository_name: str
    default_branch: str
    workflow_id: str
    release_ref_prefix: str
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime
