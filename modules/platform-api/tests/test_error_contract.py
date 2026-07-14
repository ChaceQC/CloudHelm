"""Platform API 统一错误契约测试。"""

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.exceptions import ServiceError


class FailingCommitSession:
    """最小失败 Session，用于验证数据库异常公开边界。"""

    def __init__(self) -> None:
        self.info: dict = {}
        self.rollback_called = False

    def commit(self) -> None:
        """模拟包含 SQL 与敏感参数的数据库驱动异常。"""

        raise SQLAlchemyError(
            "INSERT INTO secrets(token) VALUES ('sensitive-database-token')"
        )

    def rollback(self) -> None:
        """记录 service 是否在返回稳定错误前完成回滚。"""

        self.rollback_called = True


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


def test_base_service_database_error_hides_driver_details() -> None:
    """白盒验证数据库异常会回滚且不进入公开 ServiceError detail。"""

    session = FailingCommitSession()

    try:
        BaseService(session).commit()  # type: ignore[arg-type]
    except ServiceError as exc:
        assert exc.code == "database_error"
        assert exc.status_code == 500
        assert exc.detail is None
        assert "sensitive-database-token" not in str(exc)
    else:
        raise AssertionError("数据库提交失败必须转换为 ServiceError。")

    assert session.rollback_called is True


def test_database_error_response_hides_driver_details() -> None:
    """黑盒验证 database_error 响应保留 trace_id 但不泄露 SQL 或参数。"""

    app = create_app()

    @app.get("/__tests__/database-error")
    def raise_database_error() -> None:
        """测试专用：通过 BaseService 触发数据库提交错误。"""

        BaseService(FailingCommitSession()).commit()  # type: ignore[arg-type]

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/__tests__/database-error",
            headers={"X-Trace-Id": "database-trace-001"},
        )

    assert response.status_code == 500
    assert response.headers["X-Trace-Id"] == "database-trace-001"
    assert response.json() == {
        "code": "database_error",
        "message": "数据库写入失败。",
        "detail": None,
        "trace_id": "database-trace-001",
    }
    assert "INSERT INTO" not in response.text
    assert "sensitive-database-token" not in response.text
