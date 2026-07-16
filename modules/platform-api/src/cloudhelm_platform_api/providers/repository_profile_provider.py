"""服务端 Gitea repository profile 与 credential 解析。"""

from __future__ import annotations

import json
from pathlib import Path
import re

from pydantic import SecretStr, TypeAdapter, ValidationError

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.core.repository_config import (
    RepositoryProfileConfig,
)
from cloudhelm_platform_api.services.exceptions import ServiceError

_PROFILE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROFILE_MAP = TypeAdapter(dict[str, RepositoryProfileConfig])


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """拒绝 JSON object 内重复 key，避免配置被解析器静默覆盖。"""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repository profile JSON 存在重复 key。")
        result[key] = value
    return result


class RepositoryProfileProvider:
    """读取普通 API 不能覆盖的 repository profile 与内部 credential。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._profiles: dict[str, RepositoryProfileConfig] | None = None

    def get_profile(self, profile_key: str) -> RepositoryProfileConfig:
        """读取 profile；缺失时返回稳定调用方错误。"""

        if self._profiles is None:
            self._profiles = self._load_profiles()
        profile = self._profiles.get(profile_key)
        if profile is None:
            raise ServiceError(
                "repository_profile_not_found",
                "Repository profile 不存在。",
                422,
            )
        return profile

    def get_credential(self, credential_ref: str) -> SecretStr:
        """确认 profile 引用的 credential 已配置且非空。"""

        credential = self.settings.repository_credentials.get(
            credential_ref
        )
        if (
            credential is None
            or not credential.get_secret_value().strip()
        ):
            raise ServiceError(
                "repository_profile_unusable",
                "Repository profile credential 配置不可用。",
                503,
            )
        return credential

    def _load_profiles(self) -> dict[str, RepositoryProfileConfig]:
        """合并环境变量与可选 UTF-8 JSON 文件中的 profile。"""

        try:
            profiles = dict(self.settings.repository_profiles)
            self._validate_profile_keys(profiles)
        except ValueError as exc:
            raise ServiceError(
                "repository_profile_configuration_invalid",
                "Repository profile 配置读取或校验失败。",
                503,
            ) from exc
        configured_file = self.settings.repository_profiles_file
        if configured_file is None:
            return profiles

        try:
            raw = json.loads(
                Path(configured_file).read_text(encoding="utf-8"),
                object_pairs_hook=_strict_object_pairs,
            )
            if isinstance(raw, dict) and "profiles" in raw:
                if set(raw) != {"profiles"}:
                    raise ValueError(
                        "Repository profile wrapper 只允许 profiles 字段。"
                    )
                raw = raw["profiles"]
            file_profiles = _PROFILE_MAP.validate_python(raw)
            self._validate_profile_keys(file_profiles)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise ServiceError(
                "repository_profile_configuration_invalid",
                "Repository profile 配置文件读取或校验失败。",
                503,
            ) from exc

        duplicate_keys = sorted(set(profiles).intersection(file_profiles))
        if duplicate_keys:
            raise ServiceError(
                "repository_profile_configuration_invalid",
                "Repository profile key 在多处配置中重复。",
                503,
            )
        profiles.update(file_profiles)
        return profiles

    @staticmethod
    def _validate_profile_keys(
        profiles: dict[str, RepositoryProfileConfig],
    ) -> None:
        """Profile map key 必须与 API 可引用格式完全一致。"""

        if any(not _PROFILE_KEY.fullmatch(key) for key in profiles):
            raise ValueError("Repository profile key 格式非法。")
