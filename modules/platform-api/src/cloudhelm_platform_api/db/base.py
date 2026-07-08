"""SQLAlchemy ORM 基类和通用字段。

M2 数据底座要求所有核心表使用 UUID 主键、timezone-aware 时间字段，并
由 Alembic 迁移到 PostgreSQL。这里集中定义通用 mixin，减少各模型重复
代码并保证时间字段语义一致。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。

    SQLAlchemy 默认值使用 callable，避免模块导入时固定时间值。
    """

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """CloudHelm 平台 API 所有 ORM 模型的声明式基类。"""


class UUIDPrimaryKeyMixin:
    """为核心表提供 PostgreSQL UUID 主键。"""

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="记录唯一标识。",
    )


class TimestampMixin:
    """为需要审计时间的表提供创建和更新时间。

    `updated_at` 由 ORM 在更新时维护；数据库层后续如需触发器，可在
    独立迁移中增强，不影响当前 M2 API 契约。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="记录创建时间。",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="记录最近更新时间。",
    )
