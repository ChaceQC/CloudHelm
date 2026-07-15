"""M7 Environment ORM 模型。"""

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Environment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目的 staging/demo 远端运行环境。

    `env_profile_ref` 是服务端部署配置引用，只在内部持久化，普通 API
    响应不暴露该字段。
    """

    __tablename__ = "environments"
    __table_args__ = (
        CheckConstraint(
            "environment_type IN ('staging', 'demo')",
            name="ck_environments_type",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'degraded')",
            name="ck_environments_status",
        ),
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_environments_project_name",
        ),
        Index(
            "ix_environments_project_status_created",
            "project_id",
            "status",
            "created_at",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目 ID。",
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="项目内唯一环境名称。",
    )
    environment_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="M7 只允许 staging 或 demo。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        comment="环境状态。",
    )
    base_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="环境基础 URL；M7-1 仅用于标识和展示。",
    )
    env_profile_ref: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="受控远端 env profile 引用；API 不返回。",
    )
