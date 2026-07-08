"""健康检查响应结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """`/health` 响应 DTO。

    字段需要与 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
    保持一致，确保前端和后续部署健康检查使用同一契约。
    """

    service: str = Field(description="服务名称。")
    status: Literal["ok"] = Field(description="服务健康状态。")
    version: str = Field(description="服务版本。")
    environment: str = Field(description="运行环境。")
    timestamp: datetime = Field(description="服务端当前 UTC 时间。")
