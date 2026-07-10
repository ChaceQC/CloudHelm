"""Platform API 统一错误契约测试。"""

from fastapi.testclient import TestClient

from cloudhelm_platform_api.main import create_app


def test_unhandled_exception_returns_stable_500_with_trace_id() -> None:
    """未处理异常不得泄露堆栈或退回非 JSON 默认错误。"""

    app = create_app()

    @app.get("/__tests__/unhandled-error")
    def raise_unhandled_error() -> None:
        """测试专用：触发未处理异常。"""

        raise RuntimeError("sensitive internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__tests__/unhandled-error", headers={"X-Trace-Id": "audit-trace-001"})

    assert response.status_code == 500
    assert response.headers["X-Trace-Id"] == "audit-trace-001"
    assert response.json() == {
        "code": "internal_error",
        "message": "平台 API 发生未处理错误。",
        "detail": None,
        "trace_id": "audit-trace-001",
    }
    assert "sensitive internal detail" not in response.text
