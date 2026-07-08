"""Tool Gateway 安全策略。

策略层集中处理路径边界、敏感文件、命令限制、超时上限和审批判定。工具
实现只能调用本模块获得已校验路径或命令，不得自行拼接不受控路径。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel


class PolicyError(Exception):
    """策略拒绝时抛出的稳定异常。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolPolicy:
    """M5 本地工具策略集合。"""

    denied_dir_names = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "coverage",
    }
    denied_file_names = {
        ".env",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "known_hosts",
    }
    denied_suffixes = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
    denied_programs = {
        "rm",
        "rmdir",
        "del",
        "erase",
        "format",
        "shutdown",
        "reboot",
        "ssh",
        "scp",
        "nmap",
        "masscan",
        "nc",
        "netcat",
        "powershell",
        "pwsh",
        "cmd",
        "bash",
        "sh",
    }
    base_env_names = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"}
    allowed_env_prefixes = ("CLOUDHELM_", "PYTHON", "NODE_", "NPM_CONFIG_")

    def __init__(self, max_timeout_seconds: int = 60, max_output_chars: int = 12000) -> None:
        self.max_timeout_seconds = max_timeout_seconds
        self.max_output_chars = max_output_chars

    def requires_approval(self, risk_level: RiskLevel) -> bool:
        """判断工具风险等级是否必须审批。"""

        return risk_level in {RiskLevel.L3, RiskLevel.L4}

    def resolve_workspace_root(self, workspace_root: str | Path) -> Path:
        """解析并校验受控 workspace 根目录。"""

        root = Path(workspace_root).expanduser()
        if not root.exists() or not root.is_dir():
            raise PolicyError("workspace_not_found", "workspace_root 必须是已存在目录。")
        return root.resolve(strict=True)

    def resolve_workspace_path(
        self,
        workspace_root: str | Path,
        requested_path: str | Path,
        *,
        allow_missing: bool = False,
    ) -> Path:
        """解析 workspace 内路径并阻止越界和敏感文件访问。"""

        root = self.resolve_workspace_root(workspace_root)
        raw_path = Path(requested_path).expanduser()
        candidate = raw_path if raw_path.is_absolute() else root / raw_path
        try:
            target = candidate.resolve(strict=not allow_missing)
        except FileNotFoundError as exc:
            raise PolicyError("path_not_found", "目标路径不存在。") from exc
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise PolicyError("path_outside_workspace", "目标路径越过 workspace_root 边界。") from exc
        self.ensure_path_allowed(relative)
        return target

    def ensure_path_allowed(self, relative_path: Path) -> None:
        """校验相对路径不包含依赖目录、构建产物或敏感文件。"""

        parts = [part.lower() for part in relative_path.parts]
        if any(part in self.denied_dir_names for part in parts[:-1]):
            raise PolicyError("path_denied_directory", "目标路径位于禁止访问的依赖、构建或 Git 内部目录。")
        name = parts[-1] if parts else ""
        if name in self.denied_file_names:
            raise PolicyError("path_sensitive_file", "目标路径命中敏感文件名。")
        if name.startswith(".env.") and name != ".env.example":
            raise PolicyError("path_sensitive_file", "目标路径命中环境变量文件。")
        if any(name.endswith(suffix) for suffix in self.denied_suffixes):
            raise PolicyError("path_sensitive_file", "目标路径命中密钥、证书或私钥后缀。")

    def validate_timeout(self, timeout_seconds: int) -> int:
        """限制命令执行超时，避免长时间占用本地环境。"""

        if timeout_seconds < 1:
            raise PolicyError("timeout_too_short", "timeout_seconds 不能小于 1。")
        if timeout_seconds > self.max_timeout_seconds:
            raise PolicyError("timeout_too_long", f"timeout_seconds 不能超过 {self.max_timeout_seconds}。")
        return timeout_seconds

    def validate_command(self, command: Iterable[str]) -> list[str]:
        """校验本地命令数组，不允许 shell 字符串、交互式或高危命令。"""

        command_list = [str(item) for item in command]
        if not command_list:
            raise PolicyError("command_empty", "command 不能为空。")
        program = Path(command_list[0]).name.lower()
        if program.endswith(".exe"):
            program = program[:-4]
        if program in self.denied_programs:
            raise PolicyError("command_denied", f"M5 Sandbox Tool 不允许执行 {program}。")
        lowered_args = [item.lower() for item in command_list[1:]]
        if program in {"npm", "pnpm", "yarn"} and ("-g" in lowered_args or "--global" in lowered_args):
            raise PolicyError("command_denied", "M5 Sandbox Tool 不允许执行全局 Node 依赖安装。")
        if program in {"pip", "pip3"} and ("--user" in lowered_args or "--break-system-packages" in lowered_args):
            raise PolicyError("command_denied", "M5 Sandbox Tool 不允许污染用户或系统 Python 环境。")
        return command_list

    def build_subprocess_env(self, requested_env: dict[str, str] | None = None) -> dict[str, str]:
        """构造最小环境变量集合并应用白名单覆盖。"""

        env = {name: os.environ[name] for name in self.base_env_names if name in os.environ}
        for key, value in (requested_env or {}).items():
            upper_key = key.upper()
            if not (upper_key in self.base_env_names or upper_key.startswith(self.allowed_env_prefixes)):
                raise PolicyError("env_denied", f"环境变量 {key} 不在 M5 白名单内。")
            env[key] = str(value)
        return env
