"""Remote Agent FastAPI 只读运行信息入口。"""

from fastapi import FastAPI

from cloudhelm_remote_agent.config import Settings, get_settings
from cloudhelm_remote_agent.schemas import (
    CapabilitiesResponse,
    HealthResponse,
    VersionResponse,
)

SERVICE_NAME = "cloudhelm-remote-agent"


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建只暴露健康、版本和 capability 的 FastAPI 应用。"""

    resolved = settings or get_settings()
    app = FastAPI(
        title="CloudHelm Remote Agent",
        description=(
            "CloudHelm M7-1 Linux staging/demo Remote Agent 基础接口；"
            "当前不提供部署、自由命令、文件传输或交互终端。"
        ),
        version=resolved.version,
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["runtime"],
        summary="读取 Remote Agent 进程健康状态",
    )
    def read_health() -> HealthResponse:
        """返回无 secret、路径和控制面地址的运行元数据。"""

        return HealthResponse(
            service=SERVICE_NAME,
            status="ok",
            version=resolved.version,
            agent_id=resolved.agent_id,
            capabilities=list(resolved.capabilities),
        )

    @app.get(
        "/version",
        response_model=VersionResponse,
        tags=["runtime"],
        summary="读取 Remote Agent 版本",
    )
    def read_version() -> VersionResponse:
        """返回模块版本和稳定 Agent 身份。"""

        return VersionResponse(
            service=SERVICE_NAME,
            version=resolved.version,
            agent_id=resolved.agent_id,
        )

    @app.get(
        "/capabilities",
        response_model=CapabilitiesResponse,
        tags=["runtime"],
        summary="读取 Remote Agent capabilities",
    )
    def read_capabilities() -> CapabilitiesResponse:
        """返回当前切片真实实现的 capability。"""

        return CapabilitiesResponse(
            service=SERVICE_NAME,
            agent_id=resolved.agent_id,
            capabilities=list(resolved.capabilities),
        )

    return app
