"""Tool Registry 白盒测试。"""

from pydantic import BaseModel

import pytest

from cloudhelm_tool_gateway.gateway import ToolGateway
from cloudhelm_tool_gateway.rate_limit import SlidingWindowRateLimiter
from cloudhelm_tool_gateway.registry import ToolDeclaration, ToolRegistry
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel, ToolCallRequest
from cloudhelm_tool_gateway.tools import build_default_registry


class EmptyArgs(BaseModel):
    """测试用空参数。"""


def _handler(args: BaseModel, policy) -> dict:  # noqa: ANN001
    """测试 handler。"""

    return {"summary": "ok", "result_json": {}}


def test_default_registry_contains_m5_tools() -> None:
    """默认注册表应包含 M5 本地工具集合。"""

    tools = {tool.name for tool in build_default_registry().list_tools()}
    assert {"repo.read_file", "repo.write_file", "sandbox.run_command", "git.commit", "approval.request_remote_action"} <= tools


def test_registry_rejects_duplicate_tool_name() -> None:
    """重复工具名会被注册表拒绝。"""

    registry = ToolRegistry()
    declaration = ToolDeclaration("demo.echo", "demo", EmptyArgs, RiskLevel.L0, False, (), _handler)
    registry.register(declaration)
    with pytest.raises(ValueError):
        registry.register(declaration)


def test_gateway_rate_limit_rejects_excess_calls() -> None:
    """同一任务超过窗口配额时应在 handler 前返回稳定失败结构。"""

    registry = ToolRegistry()
    registry.register(ToolDeclaration("demo.echo", "demo", EmptyArgs, RiskLevel.L0, False, (), _handler))
    gateway = ToolGateway(registry=registry, rate_limiter=SlidingWindowRateLimiter(max_calls=1, window_seconds=60))
    request = ToolCallRequest(
        task_id="00000000-0000-0000-0000-000000000001",
        tool_name="demo.echo",
        risk_level=RiskLevel.L0,
        idempotency_key="call-1",
        arguments={},
        reason="验证限流",
    )

    assert gateway.execute(request).status == "succeeded"
    limited = gateway.execute(request.model_copy(update={"idempotency_key": "call-2"}))
    assert limited.status == "failed"
    assert limited.error_code == "rate_limit_exceeded"
    assert limited.result_json is not None
    assert limited.result_json["retry_after_seconds"] >= 1


def test_gateway_rejects_system_call_for_side_effect_tool() -> None:
    """无 AgentRun 调用副作用工具应在 handler 前失败。"""

    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(
            "demo.write",
            "demo",
            EmptyArgs,
            RiskLevel.L1,
            False,
            (),
            _handler,
            ("coder",),
            False,
        )
    )
    result = ToolGateway(registry=registry).execute(
        ToolCallRequest(
            task_id="00000000-0000-0000-0000-000000000001",
            tool_name="demo.write",
            risk_level=RiskLevel.L1,
            idempotency_key="call-system",
            arguments={},
            reason="验证系统入口权限",
        )
    )
    assert result.status == "failed"
    assert result.error_code == "agent_run_required"
