"""FastAPI 应用入口与最小可观测性实现。"""

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import cast

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.routing import BaseRoute

from sample_service import __version__
from sample_service.schemas import HealthResponse

SERVICE_NAME = "sample-service"
METRICS_REGISTRY = CollectorRegistry()

SERVICE_INFO = Gauge(
    "sample_service_info",
    "Static information about the running sample service.",
    ("service", "version"),
    registry=METRICS_REGISTRY,
)
HTTP_REQUESTS = Counter(
    "sample_service_http_requests_total",
    "Total HTTP requests handled by the sample service.",
    ("method", "route", "status_code"),
    registry=METRICS_REGISTRY,
)
HTTP_REQUEST_DURATION = Histogram(
    "sample_service_http_request_duration_seconds",
    "HTTP request duration measured by the sample service.",
    ("method", "route"),
    registry=METRICS_REGISTRY,
)
SERVICE_INFO.labels(service=SERVICE_NAME, version=__version__).set(1)


def _route_label(request: Request) -> str:
    """返回低基数路由标签，避免把任意 URL 路径写入 Prometheus 标签。"""

    route = request.scope.get("route")
    if isinstance(route, BaseRoute):
        return cast(str, getattr(route, "path", "__unmatched__"))
    return "__unmatched__"


def create_app() -> FastAPI:
    """创建示例应用。

    工厂函数让测试和后续 demo issue 实现拥有明确装配入口；当前基线有意不注册
    auth/profile 路由。
    """

    application = FastAPI(
        title="CloudHelm Sample Service",
        version=__version__,
        description="CloudHelm M6 本地开发闭环使用的最小 FastAPI fixture。",
    )

    @application.middleware("http")
    async def record_request_metrics(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """记录路由级请求数和耗时；异常请求按 500 计数后继续抛出。"""

        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = _route_label(request)
            HTTP_REQUESTS.labels(
                method=request.method,
                route=route,
                status_code=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                method=request.method,
                route=route,
            ).observe(perf_counter() - started_at)

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        """返回无外部依赖的存活状态，供本地烟测与容器健康检查使用。"""

        return HealthResponse(service=SERVICE_NAME, version=__version__)

    @application.get(
        "/metrics",
        include_in_schema=False,
        response_class=Response,
    )
    async def metrics() -> Response:
        """以 Prometheus text exposition format 暴露当前进程指标。"""

        return Response(
            content=generate_latest(METRICS_REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )

    return application


app = create_app()
