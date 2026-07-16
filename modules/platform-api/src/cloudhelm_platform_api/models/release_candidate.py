"""M7 ReleaseCandidate ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ReleaseCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """最新 M6 PR 与精确 repository snapshot 形成的候选发布。

    `binding_snapshot_json` 是可审计的安全八字段快照；内部 snapshot hash
    额外覆盖 profile key、clone URL 与 credential ref，避免配置漂移后继续发布。
    """

    __tablename__ = "release_candidates"
    __table_args__ = (
        CheckConstraint(
            """
            status IN (
              'pending_approval',
              'approved',
              'rejected',
              'published',
              'stale',
              'cancelled'
            )
            """,
            name="ck_release_candidates_status",
        ),
        CheckConstraint(
            """
            jsonb_typeof(binding_snapshot_json) = 'object'
            AND binding_snapshot_json ?& ARRAY[
              'schema_version',
              'provider',
              'repository_external_id',
              'repository_owner',
              'repository_name',
              'default_branch',
              'workflow_id',
              'release_ref_prefix'
            ]
            AND (
              binding_snapshot_json - ARRAY[
                'schema_version',
                'provider',
                'repository_external_id',
                'repository_owner',
                'repository_name',
                'default_branch',
                'workflow_id',
                'release_ref_prefix'
              ]
            ) = '{}'::jsonb
            AND binding_snapshot_json->>'schema_version'
              = 'm7.repository-binding.snapshot.v1'
            AND binding_snapshot_json->>'provider' = 'gitea'
            AND jsonb_typeof(
              binding_snapshot_json->'schema_version'
            ) = 'string'
            AND jsonb_typeof(binding_snapshot_json->'provider') = 'string'
            AND jsonb_typeof(
              binding_snapshot_json->'repository_external_id'
            ) = 'string'
            AND jsonb_typeof(
              binding_snapshot_json->'repository_owner'
            ) = 'string'
            AND jsonb_typeof(
              binding_snapshot_json->'repository_name'
            ) = 'string'
            AND jsonb_typeof(
              binding_snapshot_json->'default_branch'
            ) = 'string'
            AND jsonb_typeof(binding_snapshot_json->'workflow_id') = 'string'
            AND jsonb_typeof(
              binding_snapshot_json->'release_ref_prefix'
            ) = 'string'
            AND length(
              btrim(binding_snapshot_json->>'repository_external_id')
            ) BETWEEN 1 AND 255
            AND length(
              btrim(binding_snapshot_json->>'repository_owner')
            ) BETWEEN 1 AND 255
            AND length(
              btrim(binding_snapshot_json->>'repository_name')
            ) BETWEEN 1 AND 255
            AND length(
              btrim(binding_snapshot_json->>'default_branch')
            ) BETWEEN 1 AND 255
            AND length(
              btrim(binding_snapshot_json->>'workflow_id')
            ) BETWEEN 1 AND 512
            AND left(
              binding_snapshot_json->>'release_ref_prefix',
              11
            ) = 'refs/heads/'
            AND length(
              binding_snapshot_json->>'release_ref_prefix'
            ) BETWEEN 12 AND 240
            AND binding_snapshot_json->>'release_ref_prefix'
              !~ '[[:space:]~^:?*]'
            AND binding_snapshot_json->>'release_ref_prefix'
              !~ '[[:cntrl:]]'
            AND position(
              '[' IN binding_snapshot_json->>'release_ref_prefix'
            ) = 0
            AND position(
              chr(92) IN binding_snapshot_json->>'release_ref_prefix'
            ) = 0
            AND position(
              '..' IN binding_snapshot_json->>'release_ref_prefix'
            ) = 0
            AND position(
              '//' IN binding_snapshot_json->>'release_ref_prefix'
            ) = 0
            AND position(
              '@{' IN binding_snapshot_json->>'release_ref_prefix'
            ) = 0
            AND binding_snapshot_json->>'release_ref_prefix'
              !~ '(^|/)[.]'
            AND binding_snapshot_json->>'release_ref_prefix'
              !~ '[.]lock(/|$)'
            AND right(
              binding_snapshot_json->>'release_ref_prefix',
              1
            ) NOT IN ('.', '/')
            AND binding_snapshot_json->>'release_ref_prefix'
              NOT LIKE '%.lock'
            """,
            name="ck_release_candidates_snapshot",
        ),
        CheckConstraint(
            "binding_snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_release_candidates_snapshot_hash",
        ),
        CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_release_candidates_commit_sha",
        ),
        CheckConstraint(
            """
            remote_verified_sha IS NULL
            OR remote_verified_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
            """,
            name="ck_release_candidates_remote_sha",
        ),
        CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_release_candidates_request_hash",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_release_candidates_idempotency_key",
        ),
        CheckConstraint(
            """
            left(target_ref, 11) = 'refs/heads/'
            AND length(target_ref) BETWEEN 12 AND 1024
            AND target_ref !~ '[[:space:]~^:?*]'
            AND target_ref !~ '[[:cntrl:]]'
            AND position('[' IN target_ref) = 0
            AND position(chr(92) IN target_ref) = 0
            AND position('..' IN target_ref) = 0
            AND position('//' IN target_ref) = 0
            AND position('@{' IN target_ref) = 0
            AND target_ref !~ '(^|/)[.]'
            AND target_ref !~ '[.]lock(/|$)'
            AND right(target_ref, 1) NOT IN ('.', '/')
            AND target_ref NOT LIKE '%.lock'
            """,
            name="ck_release_candidates_target_ref",
        ),
        CheckConstraint(
            """
            (
              status = 'pending_approval'
              AND approved_at IS NULL
              AND published_at IS NULL
              AND remote_verified_sha IS NULL
            )
            OR (
              status = 'approved'
              AND approved_at IS NOT NULL
              AND published_at IS NULL
              AND remote_verified_sha IS NULL
            )
            OR (
              status = 'rejected'
              AND approved_at IS NULL
              AND published_at IS NULL
              AND remote_verified_sha IS NULL
            )
            OR (
              status = 'published'
              AND approved_at IS NOT NULL
              AND published_at IS NOT NULL
              AND remote_verified_sha IS NOT NULL
              AND remote_verified_sha = commit_sha
            )
            OR (
              status IN ('stale', 'cancelled')
              AND published_at IS NULL
              AND remote_verified_sha IS NULL
            )
            """,
            name="ck_release_candidates_lifecycle",
        ),
        CheckConstraint(
            """
            updated_at >= created_at
            AND (approved_at IS NULL OR approved_at >= created_at)
            AND (
              published_at IS NULL
              OR (
                approved_at IS NOT NULL
                AND published_at >= approved_at
              )
            )
            """,
            name="ck_release_candidates_time_order",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_release_candidates_task_idempotency",
        ),
        UniqueConstraint(
            "repository_binding_id",
            "target_ref",
            name="uq_release_candidates_binding_ref",
        ),
        UniqueConstraint(
            "pull_request_record_id",
            "binding_snapshot_sha256",
            name="uq_release_candidates_pr_snapshot",
        ),
        Index(
            "ux_release_candidates_approval",
            "approval_id",
            unique=True,
            postgresql_where=text("approval_id IS NOT NULL"),
        ),
        Index(
            "ux_release_candidates_task_active",
            "task_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_approval', 'approved')"
            ),
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目 ID。",
    )
    pull_request_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pull_request_records.id", ondelete="NO ACTION"),
        nullable=False,
        comment="候选来源 M6 PullRequestRecord。",
    )
    repository_binding_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("project_repository_bindings.id", ondelete="NO ACTION"),
        nullable=False,
        comment="候选使用的仓库绑定。",
    )
    binding_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="不含 secret 的八字段仓库绑定快照。",
    )
    binding_snapshot_sha256: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="覆盖内部绑定配置的稳定 SHA-256。",
    )
    commit_sha: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="候选对应完整 commit SHA。",
    )
    target_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端生成的完整候选发布 ref。",
    )
    request_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Candidate request canonical JSON 的稳定 SHA-256。",
    )
    approval_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="NO ACTION"),
        nullable=False,
        comment="第一道 L2 release candidate 审批。",
    )
    remote_verified_sha: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="远端 ref 发布后回读确认的 commit SHA。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending_approval",
        server_default="pending_approval",
        comment="候选发布状态。",
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="任务内候选发布幂等键。",
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="第一道审批通过时间。",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="远端候选 ref 发布完成时间。",
    )


Index(
    "ix_release_candidates_task_status_created",
    ReleaseCandidate.task_id,
    ReleaseCandidate.status,
    ReleaseCandidate.created_at.desc(),
)
Index(
    "ix_release_candidates_project_created",
    ReleaseCandidate.project_id,
    ReleaseCandidate.created_at.desc(),
)
