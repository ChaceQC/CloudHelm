"""`/health` 接口测试。"""

from fastapi.testclient import TestClient


def test_health_returns_runtime_metadata(client: TestClient) -> None:
    """验证健康检查返回真实服务元数据。"""

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "cloudhelm-platform-api"
    assert data["status"] == "ok"
    assert data["version"] == "0.4.0"
    assert data["environment"] == "test"
    assert isinstance(data["timestamp"], str)
