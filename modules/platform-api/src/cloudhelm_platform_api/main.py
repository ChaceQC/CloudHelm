"""CloudHelm 平台 API 应用入口。

本模块负责创建 FastAPI 应用、注册中间件和路由。业务规则不放在入口
文件中，后续新增 Task、Approval、Event 等能力时应继续拆到 api、
services、repositories 和 workflows 层。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cloudhelm_platform_api.api.health import router as health_router
from cloudhelm_platform_api.core.config import get_settings


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    返回:
        已注册 M1 健康检查路由和本地开发 CORS 策略的 FastAPI 应用。
    """

    settings = get_settings()
    app = FastAPI(
        title="CloudHelm Platform API",
        description="CloudHelm 平台 API。M1 仅提供真实 /health。",
        version=settings.version,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    return app


app = create_app()
