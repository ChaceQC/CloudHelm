"""服务端 RemoteTarget profile 与 machine secret 解析。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr, TypeAdapter, ValidationError

from cloudhelm_platform_api.core.config import (
    Settings,
    get_settings,
)
from cloudhelm_platform_api.core.remote_target_config import (
    RemoteTargetProfileConfig,
)
from cloudhelm_platform_api.services.exceptions import ServiceError

_PROFILE_MAP = TypeAdapter(dict[str, RemoteTargetProfileConfig])


class RemoteTargetProfileProvider:
    """读取普通 API 不能覆盖的 RemoteTarget profile 和 HMAC secret。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._profiles: dict[str, RemoteTargetProfileConfig] | None = None

    def get_profile(self, profile_key: str) -> RemoteTargetProfileConfig:
        """读取 profile；缺失时返回稳定调用方错误。"""

        if self._profiles is None:
            self._profiles = self._load_profiles()
        profile = self._profiles.get(profile_key)
        if profile is None:
            raise ServiceError(
                "remote_target_profile_not_found",
                "RemoteTarget profile 不存在。",
                422,
            )
        return profile

    def get_secret(self, credential_ref: str) -> SecretStr:
        """按内部引用读取 HMAC secret，配置错误不暴露引用或 secret。"""

        secret = self.find_secret(credential_ref)
        if secret is None:
            raise ServiceError(
                "remote_agent_credential_not_configured",
                "Remote Agent machine credential 未配置。",
                503,
            )
        if len(secret.get_secret_value().encode("utf-8")) < 32:
            raise ServiceError(
                "remote_agent_credential_too_short",
                "Remote Agent machine credential 配置不符合最小长度要求。",
                503,
            )
        return secret

    def find_secret(self, credential_ref: str) -> SecretStr | None:
        """供认证路径读取原始 secret 状态，不提前泄露配置差异。"""

        return self.settings.remote_agent_credentials.get(credential_ref)

    def _load_profiles(self) -> dict[str, RemoteTargetProfileConfig]:
        """合并环境变量与可选 UTF-8 JSON 文件中的 profile。"""

        profiles = dict(self.settings.remote_target_profiles)
        configured_file = self.settings.remote_target_profiles_file
        if configured_file is None:
            return profiles

        try:
            raw = json.loads(Path(configured_file).read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "profiles" in raw:
                raw = raw["profiles"]
            file_profiles = _PROFILE_MAP.validate_python(raw)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ServiceError(
                "remote_target_profile_configuration_invalid",
                "RemoteTarget profile 配置文件读取或校验失败。",
                503,
            ) from exc

        duplicate_keys = sorted(set(profiles).intersection(file_profiles))
        if duplicate_keys:
            raise ServiceError(
                "remote_target_profile_configuration_invalid",
                "RemoteTarget profile key 在多处配置中重复。",
                503,
            )
        profiles.update(file_profiles)
        return profiles
