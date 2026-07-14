"""允许创建和运行的分析型 subagent 角色边界。"""

from cloudhelm_platform_api.services.exceptions import ServiceError

SUPPORTED_SUBAGENT_ROLES = frozenset(
    {
        "requirement",
        "architect",
        "planner",
        "tester",
        "reviewer",
        "security",
    }
)


def normalize_subagent_role(agent_role: str) -> str:
    """规范化 spawn role，并拒绝空值或共享写角色。"""

    role = agent_role.strip()
    if not role:
        raise ServiceError(
            "invalid_subagent_role",
            "创建子 Agent 失败：agent_role 不能为空。",
            422,
        )
    ensure_supported_subagent_role(role)
    return role


def ensure_supported_subagent_role(agent_role: str) -> None:
    """阻止新建或遗留 child 使用未允许的角色。"""

    if agent_role not in SUPPORTED_SUBAGENT_ROLES:
        raise ServiceError(
            "subagent_role_not_allowed",
            "当前只允许已实现的只读或分析型 subagent 角色。",
            409,
            {"agent_role": agent_role},
        )
