"""平台 API 配置。

配置通过环境变量注入，避免把端口、环境、版本和后续外部服务地址写死在
业务代码中。M1 只暴露健康检查所需的最小配置。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """平台 API 运行配置。

    环境变量使用 `CLOUDHELM_` 前缀。后续接入数据库、Redis、CORS
    白名单和日志配置时，应继续在此集中声明并补充校验。
    """

    model_config = SettingsConfigDict(env_prefix="CLOUDHELM_", extra="ignore")

    env: str = Field(default="development", description="当前运行环境。")
    version: str = Field(default="0.1.0", description="当前服务版本。")
    service_name: str = Field(
        default="cloudhelm-platform-api",
        description="健康检查和观测日志使用的服务名。",
    )
    cors_origins: list[str] = Field(
        default=["http://127.0.0.1:5173", "http://localhost:5173"],
        description="M1 本地控制台允许访问平台 API 的来源。",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存平台 API 配置。

    返回:
        `Settings` 实例。缓存可避免每个请求重复解析环境变量。
    """

    return Settings()
