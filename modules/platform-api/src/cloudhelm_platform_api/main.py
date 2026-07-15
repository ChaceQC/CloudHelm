"""CloudHelm 平台 API 应用入口。

本模块负责创建 FastAPI 应用、注册中间件和路由。业务规则不放在入口
文件中，M2 已将 Project、Task、Requirement、Design、AgentRun、
ToolCall、Approval 与 Event 能力拆到 api、services、repositories 和
models 层。
"""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cloudhelm_platform_api.api.agent_runs import router as agent_run_router
from cloudhelm_platform_api.api.approvals import router as approval_router
from cloudhelm_platform_api.api.artifacts import router as artifact_router
from cloudhelm_platform_api.api.designs import router as design_router
from cloudhelm_platform_api.api.development_plans import router as development_plan_router
from cloudhelm_platform_api.api.environments import router as environment_router
from cloudhelm_platform_api.api.errors import register_exception_handlers
from cloudhelm_platform_api.api.events import router as event_router
from cloudhelm_platform_api.api.health import router as health_router
from cloudhelm_platform_api.api.local_development import (
    router as local_development_router,
)
from cloudhelm_platform_api.api.orchestration import router as orchestration_router
from cloudhelm_platform_api.api.projects import router as project_router
from cloudhelm_platform_api.api.pull_request_records import (
    router as pull_request_record_router,
)
from cloudhelm_platform_api.api.requirements import router as requirement_router
from cloudhelm_platform_api.api.remote_agents import router as remote_agent_router
from cloudhelm_platform_api.api.remote_targets import router as remote_target_router
from cloudhelm_platform_api.api.tasks import router as task_router
from cloudhelm_platform_api.api.tool_calls import router as tool_call_router
from cloudhelm_platform_api.api.tool_gateway import router as tool_gateway_router
from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.middleware.heartbeat_body_limit import (
    HeartbeatBodyLimitMiddleware,
)
from cloudhelm_platform_api.schemas.common import ErrorResponse
from cloudhelm_tool_gateway import create_default_gateway


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    返回:
        已注册 M1 健康检查路由和本地开发 CORS 策略的 FastAPI 应用。
    """

    settings = get_settings()
    app = FastAPI(
        title="CloudHelm Platform API",
        description=(
            "CloudHelm 平台 API。M1-M6 提供数据库驱动的 Agent 编排、"
            "受控本地开发工具、Artifact 与本地等价 PR record；M7-1 新增"
            " Environment、RemoteTarget 和 machine-auth heartbeat 基础闭环。"
        ),
        version=settings.version,
        responses={
            400: {"model": ErrorResponse, "description": "业务请求错误。"},
            404: {"model": ErrorResponse, "description": "资源不存在。"},
            409: {"model": ErrorResponse, "description": "状态冲突。"},
            422: {"model": ErrorResponse, "description": "请求参数校验失败。"},
            500: {"model": ErrorResponse, "description": "服务端错误。"},
        },
    )

    app.state.tool_gateway = create_default_gateway(
        max_calls=settings.tool_rate_limit_calls,
        window_seconds=settings.tool_rate_limit_window_seconds,
        max_timeout_seconds=settings.tool_max_timeout_seconds,
        max_output_chars=settings.tool_max_output_chars,
        allowed_workspace_roots=settings.effective_tool_workspace_roots,
    )

    @app.middleware("http")
    async def add_trace_id(request, call_next):
        """为每个请求补充 trace_id，统一错误响应和调用链排查。"""

        request.state.trace_id = request.headers.get("X-Trace-Id") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.add_middleware(
        HeartbeatBodyLimitMiddleware,
        max_body_bytes=settings.remote_agent_heartbeat_max_body_bytes,
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(project_router)
    app.include_router(environment_router)
    app.include_router(remote_target_router)
    app.include_router(remote_agent_router)
    app.include_router(task_router)
    app.include_router(requirement_router)
    app.include_router(design_router)
    app.include_router(development_plan_router)
    app.include_router(agent_run_router)
    app.include_router(tool_call_router)
    app.include_router(tool_gateway_router)
    app.include_router(artifact_router)
    app.include_router(pull_request_record_router)
    app.include_router(approval_router)
    app.include_router(event_router)
    app.include_router(orchestration_router)
    app.include_router(local_development_router)
    return app


app = create_app()
