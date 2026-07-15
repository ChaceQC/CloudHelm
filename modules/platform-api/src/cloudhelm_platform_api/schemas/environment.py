"""M7 Environment API DTO。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from cloudhelm_platform_api.schemas.common import OrmModel


class EnvironmentCreate(BaseModel):
    """创建 staging/demo Environment 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9-]{0,62}$",
        description="项目内唯一环境名称。",
    )
    environment_type: Literal["staging", "demo"] = Field(
        description="M7 只允许 staging 或 demo。",
    )
    base_url: HttpUrl = Field(description="环境基础 URL。")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        """拒绝明文 HTTP、URL 凭据、查询和片段，避免保存敏感 URL。"""

        if value.scheme != "https":
            raise ValueError("Environment base_url 必须使用 HTTPS。")
        if value.username or value.password or value.query or value.fragment:
            raise ValueError(
                "Environment base_url 不得包含凭据、query 或 fragment。"
            )
        return value


class EnvironmentRead(OrmModel):
    """不暴露内部 env profile 引用的 Environment 响应。"""

    id: UUID
    project_id: UUID
    name: str
    environment_type: Literal["staging", "demo"]
    status: Literal["active", "disabled", "degraded"]
    base_url: str
    created_at: datetime
    updated_at: datetime
