"""Sandbox Tool 测试。"""

from pathlib import Path
from uuid import uuid4

from cloudhelm_tool_gateway import RiskLevel, ToolCallRequest, create_default_gateway


def _request(arguments: dict) -> ToolCallRequest:
    """构造 sandbox.run_command 请求。"""

    return ToolCallRequest(
        task_id=uuid4(),
        tool_name="sandbox.run_command",
        risk_level=RiskLevel.L1,
        idempotency_key=str(uuid4()),
        arguments=arguments,
        reason="pytest",
    )


def test_sandbox_runs_safe_command(tmp_path: Path) -> None:
    """Sandbox Tool 能执行安全的非交互式命令。"""

    result = create_default_gateway().execute(
        _request(
            {
                "workspace_root": str(tmp_path),
                "command": ["python", "-c", "print('sandbox-ok')"],
                "timeout_seconds": 5,
            }
        )
    )
    assert result.status == "succeeded"
    assert "sandbox-ok" in (result.stdout_summary or "")


def test_sandbox_reports_non_zero_exit(tmp_path: Path) -> None:
    """非零退出码应成为可追溯失败结果。"""

    result = create_default_gateway().execute(
        _request({"workspace_root": str(tmp_path), "command": ["python", "-c", "import sys; sys.exit(3)"]})
    )
    assert result.status == "failed"
    assert result.error_code == "command_failed"


def test_sandbox_reports_timeout(tmp_path: Path) -> None:
    """命令超时应返回 command_timeout。"""

    result = create_default_gateway().execute(
        _request({"workspace_root": str(tmp_path), "command": ["python", "-c", "import time; time.sleep(2)"], "timeout_seconds": 1})
    )
    assert result.status == "failed"
    assert result.error_code == "command_timeout"
