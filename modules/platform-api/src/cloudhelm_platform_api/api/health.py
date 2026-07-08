"""健康检查 API。

`/health` 用于本地开发、前端控制台和后续部署健康检查确认服务进程
真实可用。该接口不访问数据库，因此可在依赖未初始化时用于快速诊断。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="读取平台 API 健康状态",
)
def read_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """返回平台 API 的真实运行元数据。

    参数:
        settings: 由环境变量解析得到的服务配置。

    返回:
        服务名、状态、版本、运行环境和服务端当前 UTC 时间。
    """

    return HealthResponse(
        service=settings.service_name,
        status="ok",
        version=settings.version,
        environment=settings.env,
        timestamp=datetime.now(UTC),
    )
