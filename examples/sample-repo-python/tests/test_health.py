"""健康检查黑盒测试。"""

import asyncio

import httpx

from sample_service.main import app


def test_health_returns_stable_service_status() -> None:
    """健康端点应返回可供编排器稳定判断的状态和版本。"""

    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(request_health())
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sample-service",
        "version": "0.1.0",
    }
