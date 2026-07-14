"""Sandbox Tool 测试。"""

from pathlib import Path
from uuid import uuid4

from cloudhelm_tool_gateway import RiskLevel, ToolCallRequest, create_default_gateway
from cloudhelm_tool_gateway.policies import ToolPolicy
from cloudhelm_tool_gateway.process_runner import run_process


def _request(arguments: dict) -> ToolCallRequest:
    """构造 sandbox.run_command 请求。"""

    return ToolCallRequest(
        task_id=uuid4(),
        agent_run_id=uuid4(),
        agent_type='tester',
        tool_name="sandbox.run_command",
        risk_level=RiskLevel.L1,
        idempotency_key=str(uuid4()),
        arguments=arguments,
        reason="pytest",
    )


def test_sandbox_runs_safe_command(tmp_path: Path) -> None:
    """Sandbox Tool 能执行安全的非交互式命令。"""

    result = create_default_gateway(allowed_workspace_roots=[tmp_path]).execute(
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

    result = create_default_gateway(allowed_workspace_roots=[tmp_path]).execute(
        _request({"workspace_root": str(tmp_path), "command": ["python", "-c", "import sys; sys.exit(3)"]})
    )
    assert result.status == "failed"
    assert result.error_code == "command_failed"


def test_sandbox_reports_timeout(tmp_path: Path) -> None:
    """命令超时应返回 command_timeout。"""

    result = create_default_gateway(allowed_workspace_roots=[tmp_path]).execute(
        _request({"workspace_root": str(tmp_path), "command": ["python", "-c", "import time; time.sleep(2)"], "timeout_seconds": 1})
    )
    assert result.status == "failed"
    assert result.error_code == "command_timeout"


def test_sandbox_redacts_token_from_output(tmp_path: Path) -> None:
    """命令输出中的常见 API Token 不得进入 ToolCall 摘要。"""

    token = "sk-abcdefghijklmnopqrstuvwxyz123456"
    result = create_default_gateway(allowed_workspace_roots=[tmp_path]).execute(
        _request({"workspace_root": str(tmp_path), "command": ["python", "-c", f"print('{token}')"]})
    )

    assert result.status == "succeeded"
    assert token not in (result.stdout_summary or "")
    assert "<redacted>" in (result.stdout_summary or "")


def test_sandbox_rejects_path_environment_injection(
    tmp_path: Path,
) -> None:
    """Sandbox 请求不能用 PATH 劫持受控命令解析。"""

    result = create_default_gateway(
        allowed_workspace_roots=[tmp_path]
    ).execute(
        _request(
            {
                "workspace_root": str(tmp_path),
                "command": ["python", "-c", "print('not-run')"],
                "env": {"PATH": str(tmp_path)},
            }
        )
    )

    assert result.status == "failed"
    assert result.error_code == "env_override_denied"


def test_process_runner_bounds_large_output(tmp_path: Path) -> None:
    """底层捕获只读取上限内文本，并显式标记截断。"""

    policy = ToolPolicy(allowed_workspace_roots=[tmp_path])
    result = run_process(
        ["python", "-c", "print('x' * 200000)"],
        cwd=tmp_path,
        env=policy.build_subprocess_env(),
        timeout_seconds=5,
        policy=policy,
        max_output_chars=128,
    )

    assert result.exit_code == 0
    assert len(result.stdout) <= 128
    assert result.stdout_truncated is True


def test_process_runner_bounds_output_before_timeout(
    tmp_path: Path,
) -> None:
    """超时路径同样从临时文件有界读取已产生输出。"""

    policy = ToolPolicy(allowed_workspace_roots=[tmp_path])
    result = run_process(
        [
            "python",
            "-c",
            (
                "import time;"
                "print('y' * 200000, flush=True);"
                "time.sleep(5)"
            ),
        ],
        cwd=tmp_path,
        env=policy.build_subprocess_env(),
        timeout_seconds=1,
        policy=policy,
        max_output_chars=96,
    )

    assert result.timed_out is True
    assert len(result.stdout) <= 96
    assert result.stdout_truncated is True
