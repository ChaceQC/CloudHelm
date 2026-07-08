"""数据库 Engine 与 Session 管理。

FastAPI 依赖每个请求创建一个短生命周期 `Session`，写操作由 service 层
在同一事务内提交业务记录与事件记录。测试可调用 `reset_engine_cache`
在切换环境变量后重建连接池。
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_platform_api.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """创建并缓存 SQLAlchemy Engine。

    返回:
        指向 `CLOUDHELM_DATABASE_URL` 的 Engine，启用 `pool_pre_ping` 以便
        本地 Docker PostgreSQL 重启后能自动剔除失效连接。
    """

    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """创建并缓存 Session 工厂。

    `expire_on_commit=False` 便于 service 在提交后继续将 ORM 对象转换为
    Pydantic DTO，不需要额外重新查询。
    """

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI 依赖：为单个请求提供数据库会话。

    异常时回滚当前事务，最终始终关闭连接，避免请求间共享未提交状态。
    """

    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_cache() -> None:
    """清理 Engine 和 Session 工厂缓存。

    该函数主要服务测试：测试设置新的数据库环境变量后，需要重新创建
    Engine，避免继续使用旧连接串。
    """

    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
