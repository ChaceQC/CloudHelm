"""示例服务对外 HTTP 响应模型。"""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """健康检查响应。

    `status` 保持稳定枚举，便于容器、CloudHelm 和黑盒测试判断服务是否可用。
    """

    status: Literal["ok"] = "ok"
    service: str
    version: str
