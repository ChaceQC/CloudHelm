"""Alembic 迁移环境。

迁移连接串来自 `CLOUDHELM_DATABASE_URL`，保证本地开发、测试和演示环境
使用同一套配置入口。模型 metadata 通过 `cloudhelm_platform_api.models`
统一导入，避免新增表未被迁移识别。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线生成 SQL 迁移脚本。"""

    url = get_settings().database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线执行迁移。"""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_settings().database_url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
