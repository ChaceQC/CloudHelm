"""Remote Agent 环境变量配置。

所有部署差异均从 ``CLOUDHELM_REMOTE_AGENT_*`` 环境变量读取。machine
secret 不属于 Settings 字段，只保存凭据文件位置，并在每次心跳发送前从
文件重新读取，以支持受控的原子轮换。
"""

from functools import lru_cache
from pathlib import Path
import re
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cloudhelm_remote_agent import __version__

_IDENTITY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class Settings(BaseSettings):
    """Remote Agent 运行配置。

    ``platform_api_base_url`` 只允许站点根地址，避免 URL 前缀使签名 path
    与 Platform API 实际路由发生歧义。生产环境应使用经过受控 CA 校验的
    HTTPS 地址。
    """

    model_config = SettingsConfigDict(
        env_prefix="CLOUDHELM_REMOTE_AGENT_",
        extra="ignore",
    )

    platform_api_base_url: HttpUrl = Field(
        description="Platform API 站点根地址。",
    )
    target_id: UUID = Field(
        description="Platform API 已登记的 RemoteTarget ID。",
    )
    agent_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=_IDENTITY_PATTERN,
        description="当前 Remote Agent 的稳定身份。",
    )
    key_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=_IDENTITY_PATTERN,
        description="当前 machine credential 的轮换标识。",
    )
    credential_file: Path = Field(
        description="仅包含 machine secret 的受控凭据文件。",
    )
    platform_ca_bundle: Path | None = Field(
        default=None,
        description="可选的 Platform API 受控 CA bundle；为空时使用系统信任库。",
    )
    heartbeat_seconds: float = Field(
        default=20.0,
        ge=0.1,
        le=3600.0,
        description="相邻心跳尝试的有界间隔秒数。",
    )
    request_timeout: float = Field(
        default=10.0,
        ge=0.1,
        le=120.0,
        description="心跳 HTTP connect/read/write/pool 统一超时秒数。",
    )
    version: str = Field(
        default=__version__,
        pattern=r"^\d+\.\d+\.\d+$",
        description="上报和健康检查使用的模块版本。",
    )
    capabilities: tuple[str, ...] = Field(
        default=(
            "capabilities",
            "health",
            "heartbeat",
            "version",
        ),
        min_length=1,
        max_length=32,
        description="Agent 当前真实支持的能力列表。",
    )

    @field_validator("platform_api_base_url")
    @classmethod
    def validate_platform_api_base_url(cls, value: HttpUrl) -> HttpUrl:
        """限制 base URL 不携带 path、query、fragment 或凭据。"""

        if value.username is not None or value.password is not None:
            raise ValueError("platform_api_base_url 不得携带 URL 凭据。")
        if value.scheme != "https":
            raise ValueError("platform_api_base_url 必须使用 HTTPS。")
        if value.path not in {"", "/"} or value.query or value.fragment:
            raise ValueError("platform_api_base_url 必须是无 path/query/fragment 的站点根地址。")
        return value

    @field_validator("credential_file")
    @classmethod
    def validate_credential_file_path(cls, value: Path) -> Path:
        """要求凭据位置使用绝对路径，避免 cwd 改变读取对象。"""

        if not value.is_absolute():
            raise ValueError("credential_file 必须是绝对路径。")
        return value

    @field_validator("platform_ca_bundle")
    @classmethod
    def validate_platform_ca_bundle(
        cls,
        value: Path | None,
    ) -> Path | None:
        """自定义 CA 必须是已存在的绝对普通文件。"""

        if value is None:
            return None
        if not value.is_absolute() or not value.is_file():
            raise ValueError("platform_ca_bundle 必须是已存在的绝对文件。")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        """校验 capability 格式并去重排序，保证心跳序列化稳定。"""

        normalized = tuple(sorted(set(value)))
        if len(normalized) != len(value):
            raise ValueError("capabilities 不得包含重复项。")
        if not all(_CAPABILITY_PATTERN.fullmatch(item) for item in normalized):
            raise ValueError("capabilities 包含非法名称。")
        return normalized

    @property
    def platform_api_origin(self) -> str:
        """返回不带末尾斜杠的 Platform API origin。"""

        return str(self.platform_api_base_url).rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存环境变量配置。"""

    return Settings()
