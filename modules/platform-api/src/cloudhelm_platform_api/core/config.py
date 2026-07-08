"""平台 API 配置。

配置通过环境变量注入，避免把数据库地址、端口、环境、版本和后续外部
服务地址写死在业务代码中。M2 开始接入 PostgreSQL，所有数据库连接均
从 `CLOUDHELM_DATABASE_URL` 读取，便于本地开发、测试和后续部署环境
使用不同配置。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """平台 API 运行配置。

    环境变量使用 `CLOUDHELM_` 前缀。集中声明配置可以避免业务层硬编码
    部署差异，同时让测试夹具能够通过环境变量切换隔离数据库。
    """

    model_config = SettingsConfigDict(env_prefix="CLOUDHELM_", extra="ignore")

    env: str = Field(default="development", description="当前运行环境。")
    version: str = Field(default="0.2.0", description="当前服务版本。")
    service_name: str = Field(
        default="cloudhelm-platform-api",
        description="健康检查和观测日志使用的服务名。",
    )
    database_url: str = Field(
        default="postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm",
        description="SQLAlchemy 数据库连接串，M2 默认指向本地 PostgreSQL。",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis 预留连接串；M2 暂不接入生产路径。",
    )
    cors_origins: list[str] = Field(
        default=["http://127.0.0.1:5173", "http://localhost:5173"],
        description="本地控制台允许访问平台 API 的来源。",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存平台 API 配置。

    返回:
        `Settings` 实例。缓存可避免每个请求重复解析环境变量。
    """

    return Settings()
