"""ToolPolicy 白盒测试。"""

from pathlib import Path

import pytest

from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel


def test_policy_blocks_path_traversal(tmp_path: Path) -> None:
    """路径解析必须阻止越过 workspace_root。"""

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    policy = ToolPolicy()
    with pytest.raises(PolicyError) as error:
        policy.resolve_workspace_path(tmp_path, outside)
    assert error.value.code == "path_outside_workspace"


def test_policy_blocks_sensitive_files(tmp_path: Path) -> None:
    """敏感文件名和私钥后缀不可读写。"""

    secret = tmp_path / ".env"
    secret.write_text("TOKEN=1", encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        ToolPolicy().resolve_workspace_path(tmp_path, ".env")
    assert error.value.code == "path_sensitive_file"


def test_policy_requires_approval_for_l3_l4() -> None:
    """L3/L4 风险等级必须进入审批。"""

    policy = ToolPolicy()
    assert not policy.requires_approval(RiskLevel.L2)
    assert policy.requires_approval(RiskLevel.L3)
    assert policy.requires_approval(RiskLevel.L4)


def test_policy_blocks_denied_commands() -> None:
    """Sandbox 命令策略拒绝高危程序。"""

    with pytest.raises(PolicyError) as error:
        ToolPolicy().validate_command(["ssh", "demo"])
    assert error.value.code == "command_denied"
