"""Prometheus 指标端点黑盒测试。"""

import asyncio

import httpx
from prometheus_client import CONTENT_TYPE_LATEST

from sample_service.main import app


def test_metrics_returns_prometheus_text_and_health_observation() -> None:
    """抓取结果应包含服务信息及按路由模板聚合的健康请求指标。"""

    async def request_health_and_metrics() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            health_response = await client.get("/health")
            metrics_response = await client.get("/metrics")
            return health_response, metrics_response

    health_response, metrics_response = asyncio.run(request_health_and_metrics())
    assert health_response.status_code == 200
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"] == CONTENT_TYPE_LATEST
    assert "# HELP sample_service_info" in metrics_response.text
    assert (
        'sample_service_info{service="sample-service",version="0.1.0"} 1.0'
        in metrics_response.text
    )
    assert (
        'sample_service_http_requests_total{method="GET",route="/health",'
        'status_code="200"}'
        in metrics_response.text
    )
