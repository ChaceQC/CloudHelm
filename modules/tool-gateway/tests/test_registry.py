"""Tool Registry 白盒测试。"""

from pydantic import BaseModel

import pytest

from cloudhelm_tool_gateway.registry import ToolDeclaration, ToolRegistry
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel
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
