"""`/health` 接口测试。"""

from fastapi.testclient import TestClient

from cloudhelm_platform_api.main import create_app


def test_health_returns_runtime_metadata() -> None:
    """验证健康检查返回真实服务元数据。"""

    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "cloudhelm-platform-api"
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["environment"] == "development"
    assert isinstance(data["timestamp"], str)
