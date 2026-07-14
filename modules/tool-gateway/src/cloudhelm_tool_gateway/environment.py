"""Tool Gateway 子进程环境变量白名单与注入防护。"""

import os

from cloudhelm_tool_gateway.policy_errors import PolicyError

BASE_ENV_NAMES = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LANG",
}
ALLOWED_ENV_PREFIXES = ("CLOUDHELM_", "PYTHON", "NODE_", "NPM_CONFIG_")
DENIED_REQUESTED_ENV_NAMES = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "HOME",
    "USERPROFILE",
    "PYTHONHOME",
    "PYTHONINSPECT",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "NODE_OPTIONS",
    "NPM_CONFIG_USERCONFIG",
}


def build_safe_subprocess_env(
    requested_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """继承最小宿主环境，并拒绝命令解析与解释器启动注入。"""

    env = {
        name: os.environ[name]
        for name in BASE_ENV_NAMES
        if name in os.environ
    }
    for key, value in (requested_env or {}).items():
        upper_key = key.upper()
        if (
            not key
            or "=" in key
            or "\x00" in key
            or "\x00" in str(value)
        ):
            raise PolicyError(
                "env_invalid",
                "环境变量名称和值不能包含空名称、等号或 NUL。",
            )
        if upper_key in DENIED_REQUESTED_ENV_NAMES:
            raise PolicyError(
                "env_override_denied",
                f"环境变量 {key} 会改变解释器或命令解析边界。",
            )
        if not (
            upper_key in BASE_ENV_NAMES
            or upper_key.startswith(ALLOWED_ENV_PREFIXES)
        ):
            raise PolicyError(
                "env_denied",
                f"环境变量 {key} 不在 Tool Gateway 白名单内。",
            )
        env[key] = str(value)
    return env
