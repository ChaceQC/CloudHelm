"""Workflow Engine 独立 Engine 与短 Session 工厂。"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_workflow_engine.config import get_workflow_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """创建启用断线探测的 PostgreSQL Engine。"""

    settings = get_workflow_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """返回不跨 handler 共享的短 Session 工厂。"""

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def reset_database_cache() -> None:
    """测试切换数据库 URL 时释放连接池和缓存。"""

    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
