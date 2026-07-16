"""M7 ProjectRepositoryBinding ORM 模型。"""

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ProjectRepositoryBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """由服务端 repository profile 物化的项目唯一远端仓库绑定。

    `clone_url` 和 `credential_ref` 只供内部发布流程使用，不进入普通 API、
    EventLog 或 ReleaseCandidate 的安全 snapshot JSON。
    """

    __tablename__ = "project_repository_bindings"
    __table_args__ = (
        CheckConstraint(
            "provider = 'gitea'",
            name="ck_project_repository_bindings_provider",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_project_repository_bindings_status",
        ),
        CheckConstraint(
            "profile_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'",
            name="ck_project_repository_bindings_profile_key",
        ),
        CheckConstraint(
            """
            length(btrim(repository_external_id)) BETWEEN 1 AND 255
            AND length(btrim(repository_owner)) BETWEEN 1 AND 255
            AND length(btrim(repository_name)) BETWEEN 1 AND 255
            """,
            name="ck_project_repository_bindings_identity",
        ),
        CheckConstraint(
            """
            clone_url ~ '^https://[^[:space:]]+$'
            AND clone_url !~ '^https://[^/]*@'
            """,
            name="ck_project_repository_bindings_clone_url",
        ),
        CheckConstraint(
            """
            length(btrim(default_branch)) BETWEEN 1 AND 255
            AND length(btrim(credential_ref)) BETWEEN 1 AND 512
            AND length(btrim(workflow_id)) BETWEEN 1 AND 512
            """,
            name="ck_project_repository_bindings_config",
        ),
        CheckConstraint(
            """
            left(release_ref_prefix, 11) = 'refs/heads/'
            AND length(release_ref_prefix) BETWEEN 12 AND 240
            AND release_ref_prefix !~ '[[:space:]~^:?*]'
            AND release_ref_prefix !~ '[[:cntrl:]]'
            AND position('[' IN release_ref_prefix) = 0
            AND position(chr(92) IN release_ref_prefix) = 0
            AND position('..' IN release_ref_prefix) = 0
            AND position('//' IN release_ref_prefix) = 0
            AND position('@{' IN release_ref_prefix) = 0
            AND release_ref_prefix !~ '(^|/)[.]'
            AND release_ref_prefix !~ '[.]lock(/|$)'
            AND right(release_ref_prefix, 1) NOT IN ('.', '/')
            AND release_ref_prefix NOT LIKE '%.lock'
            """,
            name="ck_project_repository_bindings_release_ref_prefix",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_project_repository_bindings_time_order",
        ),
        UniqueConstraint(
            "project_id",
            name="uq_project_repository_bindings_project",
        ),
        UniqueConstraint(
            "provider",
            "repository_external_id",
            name="uq_project_repository_bindings_external",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目 ID。",
    )
    provider: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="gitea",
        server_default="gitea",
        comment="M7 固定为 gitea。",
    )
    profile_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端 repository profile key。",
    )
    repository_external_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Gitea repository 稳定外部 ID。",
    )
    repository_owner: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="仓库 owner。",
    )
    repository_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="仓库名称。",
    )
    clone_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端受控 HTTPS clone URL；API 不返回。",
    )
    default_branch: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="远端仓库默认分支。",
    )
    credential_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端 credential 引用；API 不返回。",
    )
    workflow_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="受控 Gitea workflow 文件标识。",
    )
    release_ref_prefix: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="候选发布 ref 的完整受控前缀。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        server_default="active",
        comment="绑定状态。",
    )


Index(
    "ux_project_repository_bindings_owner_name",
    ProjectRepositoryBinding.provider,
    func.lower(ProjectRepositoryBinding.repository_owner),
    func.lower(ProjectRepositoryBinding.repository_name),
    unique=True,
)
Index(
    "ix_project_repository_bindings_status_updated",
    ProjectRepositoryBinding.status,
    ProjectRepositoryBinding.updated_at.desc(),
)
