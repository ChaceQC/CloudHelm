"""M7 CIRun ORM 模型。"""

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class CIRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """唯一 Gitea workflow dispatch 对应的 CI 权威记录。

    本表只保存受控 identity、状态和不可变制品证据；token、credential、
    webhook 原文与原始 CI 日志不进入该模型。
    """

    __tablename__ = "ci_runs"
    __table_args__ = (
        CheckConstraint("provider = 'gitea'", name="ck_ci_runs_provider"),
        CheckConstraint(
            """
            status IN (
              'triggered', 'running', 'passed', 'failed', 'cancelled'
            )
            """,
            name="ck_ci_runs_status",
        ),
        CheckConstraint(
            """
            length(btrim(repository_external_id)) BETWEEN 1 AND 255
            AND repository_external_id !~ '[[:cntrl:]]'
            """,
            name="ck_ci_runs_repository_identity",
        ),
        CheckConstraint(
            """
            (
              external_run_id IS NULL
              OR (
                length(btrim(external_run_id)) BETWEEN 1 AND 255
                AND external_run_id !~ '[[:cntrl:]]'
              )
            )
            AND (
              external_job_id IS NULL
              OR (
                external_run_id IS NOT NULL
                AND length(btrim(external_job_id)) BETWEEN 1 AND 255
                AND external_job_id !~ '[[:cntrl:]]'
              )
            )
            """,
            name="ck_ci_runs_external_identity",
        ),
        CheckConstraint(
            """
            length(btrim(workflow_id)) BETWEEN 1 AND 512
            AND workflow_id !~ '[[:cntrl:]]'
            """,
            name="ck_ci_runs_workflow_identity",
        ),
        CheckConstraint(
            """
            length(btrim(workflow_revision)) BETWEEN 1 AND 255
            AND workflow_revision !~ '[[:cntrl:]]'
            """,
            name="ck_ci_runs_workflow_revision",
        ),
        CheckConstraint(
            """
            left(source_ref, 11) = 'refs/heads/'
            AND length(source_ref) BETWEEN 12 AND 512
            AND source_ref !~ '[[:space:]~^:?*]'
            AND source_ref !~ '[[:cntrl:]]'
            AND position('[' IN source_ref) = 0
            AND position(chr(92) IN source_ref) = 0
            AND position('..' IN source_ref) = 0
            AND position('//' IN source_ref) = 0
            AND position('@{' IN source_ref) = 0
            AND source_ref !~ '(^|/)[.]'
            AND source_ref !~ '[.]lock(/|$)'
            AND right(source_ref, 1) NOT IN ('.', '/')
            AND source_ref NOT LIKE '%.lock'
            """,
            name="ck_ci_runs_source_ref",
        ),
        CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_ci_runs_commit_sha",
        ),
        CheckConstraint(
            """
            provider_head_sha IS NULL
            OR (
              provider_head_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
              AND provider_head_sha = commit_sha
            )
            """,
            name="ck_ci_runs_provider_head_sha",
        ),
        CheckConstraint(
            """
            (
              image_index_digest IS NULL
              OR image_index_digest ~ '^sha256:[0-9a-f]{64}$'
            )
            AND (
              platform_manifest_digest IS NULL
              OR platform_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
            )
            """,
            name="ck_ci_runs_digests",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_ci_runs_idempotency_key",
        ),
        CheckConstraint(
            """
            (
              last_event_action IS NULL
              AND last_event_status IS NULL
              AND last_delivery_id IS NULL
              AND provider_updated_at IS NULL
            )
            OR (
              last_event_action IS NOT NULL
              AND last_event_status IS NOT NULL
              AND last_delivery_id IS NOT NULL
              AND length(btrim(last_event_action)) BETWEEN 1 AND 128
              AND length(btrim(last_event_status)) BETWEEN 1 AND 128
              AND length(btrim(last_delivery_id)) BETWEEN 1 AND 255
              AND last_event_action !~ '[[:cntrl:]]'
              AND last_event_status !~ '[[:cntrl:]]'
              AND last_delivery_id !~ '[[:cntrl:]]'
              AND provider_updated_at IS NOT NULL
            )
            """,
            name="ck_ci_runs_provider_event_group",
        ),
        CheckConstraint(
            """
            (
              status = 'triggered'
              AND started_at IS NULL
              AND finished_at IS NULL
              AND artifact_manifest_id IS NULL
              AND image_index_digest IS NULL
              AND platform_manifest_digest IS NULL
            )
            OR (
              status = 'running'
              AND external_run_id IS NOT NULL
              AND started_at IS NOT NULL
              AND finished_at IS NULL
              AND artifact_manifest_id IS NULL
              AND image_index_digest IS NULL
              AND platform_manifest_digest IS NULL
            )
            OR (
              status = 'passed'
              AND external_run_id IS NOT NULL
              AND started_at IS NOT NULL
              AND finished_at IS NOT NULL
              AND provider_head_sha IS NOT NULL
              AND artifact_manifest_id IS NOT NULL
              AND image_index_digest IS NOT NULL
              AND platform_manifest_digest IS NOT NULL
            )
            OR (
              status IN ('failed', 'cancelled')
              AND finished_at IS NOT NULL
              AND artifact_manifest_id IS NULL
              AND image_index_digest IS NULL
              AND platform_manifest_digest IS NULL
            )
            """,
            name="ck_ci_runs_lifecycle",
        ),
        CheckConstraint(
            """
            updated_at >= created_at
            AND (started_at IS NULL OR started_at >= created_at)
            AND (
              finished_at IS NULL
              OR finished_at >= COALESCE(started_at, created_at)
            )
            """,
            name="ck_ci_runs_time_order",
        ),
        UniqueConstraint(
            "release_candidate_id",
            name="uq_ci_runs_release_candidate",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_ci_runs_task_idempotency",
        ),
        Index(
            "ux_ci_runs_provider_repository_run",
            "provider",
            "repository_external_id",
            "external_run_id",
            unique=True,
            postgresql_where=text("external_run_id IS NOT NULL"),
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
        comment="来源 PullRequestRecord。",
    )
    release_candidate_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("release_candidates.id", ondelete="NO ACTION"),
        nullable=False,
        comment="唯一 ReleaseCandidate。",
    )
    provider: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="gitea",
        server_default="gitea",
        comment="M7 固定为 gitea。",
    )
    repository_external_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Gitea repository 稳定外部 ID。",
    )
    external_run_id: Mapped[str | None] = mapped_column(
        Text,
        comment="Gitea run ID；dispatch 接受后可暂时为空。",
    )
    external_job_id: Mapped[str | None] = mapped_column(
        Text,
        comment="Gitea job ID。",
    )
    workflow_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端受控 workflow 标识。",
    )
    workflow_revision: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="有界 opaque workflow revision。",
    )
    source_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="完整受控 candidate ref。",
    )
    commit_sha: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="精确 40/64 位 commit SHA。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="triggered",
        server_default="triggered",
        comment="CI 生命周期状态。",
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Task 内 CI 创建幂等键。",
    )
    last_event_action: Mapped[str | None] = mapped_column(
        Text,
        comment="最后一次接受的 provider event action。",
    )
    last_event_status: Mapped[str | None] = mapped_column(
        Text,
        comment="最后一次接受的 provider event status。",
    )
    last_delivery_id: Mapped[str | None] = mapped_column(
        Text,
        comment="最后一次安全幂等 delivery 线索。",
    )
    provider_head_sha: Mapped[str | None] = mapped_column(
        Text,
        comment="provider 回报的 head SHA。",
    )
    provider_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="provider 记录的更新时间。",
    )
    artifact_manifest_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="NO ACTION"),
        comment="通过 CI 的 manifest Artifact。",
    )
    image_index_digest: Mapped[str | None] = mapped_column(
        Text,
        comment="不可变 OCI image index digest。",
    )
    platform_manifest_digest: Mapped[str | None] = mapped_column(
        Text,
        comment="CloudHelm platform manifest digest。",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="CI 开始时间。",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="CI 终态时间。",
    )


Index(
    "ix_ci_runs_task_created",
    CIRun.task_id,
    CIRun.created_at.desc(),
    CIRun.id.desc(),
)
Index(
    "ix_ci_runs_project_created",
    CIRun.project_id,
    CIRun.created_at.desc(),
    CIRun.id.desc(),
)
