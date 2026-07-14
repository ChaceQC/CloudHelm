"""M6 Role Instructions 与 Tool Gateway 权限一致性测试。"""

from cloudhelm_agent_runtime.instructions import ROLE_ALLOWED_TOOLS
from cloudhelm_tool_gateway import create_default_gateway


REQUIRED_DOMAIN_TOOLS = {
    "scaffold": {"scaffold.prepare_workspace"},
    "coder": {
        "repo.write_file",
        "sandbox.run_command",
        "git.create_branch",
        "git.status",
        "git.diff",
    },
    "tester": {"test.run_pytest", "repo.read_file"},
    "reviewer": {"repo.read_file", "git.diff"},
    "security": {
        "security.run_bandit",
        "security.run_pip_audit",
    },
}


def test_m6_role_contract_contains_each_required_domain_tool() -> None:
    """本地 Provider 的工具计划必须是角色声明工具的子集。"""

    for agent_type, required_tools in REQUIRED_DOMAIN_TOOLS.items():
        assert required_tools.issubset(ROLE_ALLOWED_TOOLS[agent_type])

    assert "sandbox.run_command" not in ROLE_ALLOWED_TOOLS["scaffold"]
    assert "sandbox.run_command" not in ROLE_ALLOWED_TOOLS["tester"]
    assert "sandbox.run_command" not in ROLE_ALLOWED_TOOLS["security"]


def test_m6_role_contract_matches_gateway_agent_permissions() -> None:
    """Role Instructions 声明的工具必须同时允许对应 Agent 调用。"""

    gateway = create_default_gateway()
    for agent_type, tool_names in ROLE_ALLOWED_TOOLS.items():
        for tool_name in tool_names:
            declaration = gateway.registry.get(tool_name)
            assert declaration is not None, (agent_type, tool_name)
            assert agent_type in declaration.allowed_agent_types, (
                agent_type,
                tool_name,
            )
