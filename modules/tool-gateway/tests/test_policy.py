"""ToolPolicy 白盒测试。"""

from pathlib import Path

import pytest

from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel


def test_policy_blocks_path_traversal(tmp_path: Path) -> None:
    """路径解析必须阻止越过 workspace_root。"""

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    policy = ToolPolicy(allowed_workspace_roots=[tmp_path])
    with pytest.raises(PolicyError) as error:
        policy.resolve_workspace_path(tmp_path, outside)
    assert error.value.code == "path_outside_workspace"


def test_policy_blocks_sensitive_files(tmp_path: Path) -> None:
    """敏感文件名和私钥后缀不可读写。"""

    secret = tmp_path / ".env"
    secret.write_text("TOKEN=1", encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        ToolPolicy(allowed_workspace_roots=[tmp_path]).resolve_workspace_path(tmp_path, ".env")
    assert error.value.code == "path_sensitive_file"


@pytest.mark.parametrize("directory", [".git", ".venv", "node_modules"])
def test_policy_blocks_exact_denied_directory(
    tmp_path: Path,
    directory: str,
) -> None:
    """目标本身就是禁止目录时也必须拒绝。"""

    (tmp_path / directory).mkdir()
    policy = ToolPolicy(allowed_workspace_roots=[tmp_path])
    with pytest.raises(PolicyError) as error:
        policy.resolve_workspace_path(tmp_path, directory)
    assert error.value.code == "path_denied_directory"


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


def test_policy_requires_agent_run_for_side_effect_tool() -> None:
    """有副作用工具不能通过无 AgentRun 的系统入口绕过最小权限。"""

    with pytest.raises(PolicyError) as error:
        ToolPolicy().ensure_system_call_allowed(None, False)
    assert error.value.code == "agent_run_required"


def test_policy_requires_complete_agent_context() -> None:
    """AgentRun ID 与 Agent 类型缺少任一项都必须拒绝。"""

    policy = ToolPolicy()
    with pytest.raises(PolicyError) as missing_id:
        policy.ensure_agent_context(None, "coder")
    assert missing_id.value.code == "invalid_agent_context"

    with pytest.raises(PolicyError) as missing_type:
        policy.ensure_agent_context("run-id", None)
    assert missing_type.value.code == "invalid_agent_context"


def test_create_workspace_directories_blocks_symlink_escape(tmp_path: Path) -> None:
    """创建缺失父目录时仍应拒绝已存在的越界 symlink。"""

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 环境未允许创建目录 symlink。")

    with pytest.raises(PolicyError) as error:
        ToolPolicy(allowed_workspace_roots=[tmp_path]).create_workspace_directories(tmp_path, link / "nested")
    assert error.value.code == "path_outside_workspace"


def test_policy_denies_unconfigured_or_outside_workspace(tmp_path: Path) -> None:
    """未配置允许根目录时默认拒绝，允许根目录也不能访问相邻路径。"""

    with pytest.raises(PolicyError) as unconfigured:
        ToolPolicy().resolve_workspace_root(tmp_path)
    assert unconfigured.value.code == "workspace_not_allowed"

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    policy = ToolPolicy(allowed_workspace_roots=[allowed])
    assert policy.resolve_workspace_root(allowed) == allowed.resolve()
    with pytest.raises(PolicyError) as denied:
        policy.resolve_workspace_root(outside)
    assert denied.value.code == "workspace_not_allowed"


@pytest.mark.parametrize(
    "name",
    ["PATH", "PYTHONPATH", "PYTHONSTARTUP", "NODE_OPTIONS"],
)
def test_policy_blocks_environment_resolution_injection(name: str) -> None:
    """调用方不得覆盖命令解析或解释器启动环境。"""

    with pytest.raises(PolicyError) as error:
        ToolPolicy().build_subprocess_env({name: "attacker-controlled"})
    assert error.value.code == "env_override_denied"
