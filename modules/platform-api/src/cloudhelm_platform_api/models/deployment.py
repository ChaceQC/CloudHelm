"""M7 Deployment ORM 模型。"""

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


class Deployment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """第二道 L3 Approval 约束下的远端部署权威记录。

    ReleasePlan、OCI digest、Remote Agent operation 和健康/失败摘要在本表形成
    可审计链；真正的状态推进和跨表一致性由后续 service 在锁内完成。
    """

    __tablename__ = "deployments"
    __table_args__ = (
        CheckConstraint(
            """
            status IN (
              'planned', 'pending_approval', 'queued', 'deploying',
              'verifying', 'healthy', 'unhealthy', 'failed',
              'rollback_requested', 'cancelled'
            )
            """,
            name="ck_deployments_status",
        ),
        CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_deployments_commit_sha",
        ),
        CheckConstraint(
            """
            length(btrim(image_ref)) BETWEEN 1 AND 512
            AND image_ref !~ '[[:space:][:cntrl:]]'
            AND image_ref ~ '^[^@?#[:space:]\\\\]+@sha256:[0-9a-f]{64}$'
            AND image_ref !~ '^[A-Za-z][A-Za-z0-9+.-]*://'
            AND right(image_ref, length(image_digest) + 1)
              = '@' || image_digest
            """,
            name="ck_deployments_image_ref",
        ),
        CheckConstraint(
            """
            image_digest ~ '^sha256:[0-9a-f]{64}$'
            AND platform_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
            """,
            name="ck_deployments_digests",
        ),
        CheckConstraint(
            """
            length(btrim(release_version)) BETWEEN 1 AND 128
            AND release_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            """,
            name="ck_deployments_release_version",
        ),
        CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_deployments_request_hash",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_deployments_idempotency_key",
        ),
        CheckConstraint(
            """
            health_summary_json IS NULL
            OR jsonb_typeof(health_summary_json)
              IS NOT DISTINCT FROM 'object'
            """,
            name="ck_deployments_health_summary_object",
        ),
        CheckConstraint(
            """
            health_summary_json IS NULL
            OR jsonb_typeof(health_summary_json) IS DISTINCT FROM 'object'
            OR (
              jsonb_array_length(
                jsonb_path_query_array(
                  health_summary_json,
                  '$.keyvalue()'
                )
              ) <= 32
              AND NOT jsonb_path_exists(
                health_summary_json,
                '$.keyvalue() ? (!(@.key like_regex "^[a-z][a-z0-9_]{0,63}$"))'
              )
              AND NOT jsonb_path_exists(
                health_summary_json,
                '$.keyvalue() ? (@.key like_regex "(^|_)(token|tokens|secret|secrets|credential|credentials|password|passwords|cookie|cookies|authorization|raw_logs|stdout|stderr|log|logs)(_|$)" flag "i")'
              )
              AND NOT jsonb_path_exists(
                health_summary_json,
                '$.* ? (@.type() == "array" || @.type() == "object")'
              )
              AND NOT jsonb_path_exists(
                health_summary_json,
                '$.* ? (@.type() == "string" && @ like_regex "^.{255}.{255}.{3}" flag "s")'
              )
            )
            """,
            name="ck_deployments_health_summary_safe",
        ),
        CheckConstraint(
            """
            (
              status = 'failed'
              AND failure_code IS NOT NULL
              AND failure_code ~ '^[a-z][a-z0-9_]{0,127}$'
              AND (
                failure_summary IS NULL
                OR (
                  length(btrim(failure_summary)) BETWEEN 1 AND 2048
                  AND failure_summary !~ '[[:cntrl:]]'
                )
              )
            )
            OR (
              status <> 'failed'
              AND failure_code IS NULL
              AND failure_summary IS NULL
            )
            """,
            name="ck_deployments_failure_evidence",
        ),
        CheckConstraint(
            """
            (
              status = 'planned'
              AND approval_id IS NULL
              AND approved_by_actor IS NULL
            )
            OR (
              status = 'pending_approval'
              AND approval_id IS NOT NULL
              AND approved_by_actor IS NULL
            )
            OR (
              status IN (
                'queued', 'deploying', 'verifying', 'healthy', 'unhealthy',
                'rollback_requested'
              )
              AND approval_id IS NOT NULL
              AND approved_by_actor IS NOT NULL
            )
            OR (
              status IN ('failed', 'cancelled')
              AND (
                approved_by_actor IS NULL
                OR approval_id IS NOT NULL
              )
            )
            """,
            name="ck_deployments_approval_lifecycle",
        ),
        CheckConstraint(
            """
            (
              status IN ('planned', 'pending_approval', 'queued')
              AND remote_operation_id IS NULL
              AND started_at IS NULL
              AND finished_at IS NULL
            )
            OR (
              status IN ('deploying', 'verifying')
              AND remote_operation_id IS NOT NULL
              AND started_at IS NOT NULL
              AND finished_at IS NULL
            )
            OR (
              status IN ('healthy', 'unhealthy', 'rollback_requested')
              AND remote_operation_id IS NOT NULL
              AND started_at IS NOT NULL
              AND finished_at IS NOT NULL
            )
            OR (
              status IN ('failed', 'cancelled')
              AND finished_at IS NOT NULL
              AND (
                (
                  remote_operation_id IS NULL
                  AND started_at IS NULL
                )
                OR (
                  remote_operation_id IS NOT NULL
                  AND started_at IS NOT NULL
                )
              )
            )
            """,
            name="ck_deployments_operation_lifecycle",
        ),
        CheckConstraint(
            """
            status NOT IN ('healthy', 'unhealthy', 'rollback_requested')
            OR health_summary_json IS NOT NULL
            """,
            name="ck_deployments_health_lifecycle",
        ),
        CheckConstraint(
            """
            (
              status = 'rollback_requested'
              AND rollback_candidate_id IS NOT NULL
              AND rollback_request_artifact_id IS NOT NULL
              AND rollback_candidate_id <> id
            )
            OR (
              status <> 'rollback_requested'
              AND rollback_candidate_id IS NULL
              AND rollback_request_artifact_id IS NULL
            )
            """,
            name="ck_deployments_rollback",
        ),
        CheckConstraint(
            """
            length(btrim(requested_by_actor)) BETWEEN 1 AND 255
            AND requested_by_actor !~ '[[:cntrl:]]'
            AND (
              approved_by_actor IS NULL
              OR (
                length(btrim(approved_by_actor)) BETWEEN 1 AND 255
                AND approved_by_actor !~ '[[:cntrl:]]'
                AND approval_id IS NOT NULL
              )
            )
            AND (
              remote_operation_id IS NULL
              OR (
                length(btrim(remote_operation_id)) BETWEEN 1 AND 255
                AND remote_operation_id !~ '[[:cntrl:]]'
              )
            )
            """,
            name="ck_deployments_actor_fields",
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
            name="ck_deployments_time_order",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_deployments_task_idempotency",
        ),
        UniqueConstraint(
            "environment_id",
            "release_version",
            name="uq_deployments_environment_release_version",
        ),
        Index(
            "ux_deployments_approval",
            "approval_id",
            unique=True,
            postgresql_where=text("approval_id IS NOT NULL"),
        ),
        Index(
            "ux_deployments_remote_target_operation",
            "remote_target_id",
            "remote_operation_id",
            unique=True,
            postgresql_where=text("remote_operation_id IS NOT NULL"),
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
    environment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="NO ACTION"),
        nullable=False,
        comment="目标 staging/demo Environment。",
    )
    remote_target_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("remote_targets.id", ondelete="NO ACTION"),
        nullable=False,
        comment="执行部署的 Linux RemoteTarget。",
    )
    ci_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ci_runs.id", ondelete="NO ACTION"),
        nullable=False,
        comment="提供不可变制品的 CIRun。",
    )
    release_plan_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="NO ACTION"),
        nullable=False,
        comment="不可变 ReleasePlan Artifact。",
    )
    commit_sha: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="精确 40/64 位 commit SHA。",
    )
    image_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="包含不可变 digest 的 OCI image ref。",
    )
    image_digest: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="不可变 OCI image digest。",
    )
    platform_manifest_digest: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="CloudHelm platform manifest digest。",
    )
    release_version: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Environment 内唯一发布版本。",
    )
    request_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="deployment canonical request SHA-256。",
    )
    approval_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="NO ACTION"),
        comment="第二道 L3 deployment Approval。",
    )
    remote_operation_id: Mapped[str | None] = mapped_column(
        Text,
        comment="Remote Agent 幂等 operation ID。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="planned",
        server_default="planned",
        comment="部署生命周期状态。",
    )
    health_summary_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        comment="有界脱敏健康摘要。",
    )
    failure_code: Mapped[str | None] = mapped_column(
        Text,
        comment="稳定失败码。",
    )
    failure_summary: Mapped[str | None] = mapped_column(
        Text,
        comment="有界脱敏失败摘要。",
    )
    requested_by_actor: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="请求者兼容投影。",
    )
    approved_by_actor: Mapped[str | None] = mapped_column(
        Text,
        comment="审批者兼容投影。",
    )
    dispatched_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="执行部署调度的 AgentRun。",
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Task 内部署幂等键。",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Remote Agent operation 开始时间。",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="部署终态时间。",
    )
    rollback_candidate_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="NO ACTION"),
        comment="历史 Deployment 回滚候选。",
    )
    rollback_request_artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="NO ACTION"),
        comment="仅描述回滚请求的 Artifact。",
    )


Index(
    "ix_deployments_task_created",
    Deployment.task_id,
    Deployment.created_at.desc(),
    Deployment.id.desc(),
)
Index(
    "ix_deployments_project_created",
    Deployment.project_id,
    Deployment.created_at.desc(),
    Deployment.id.desc(),
)
Index(
    "ix_deployments_environment_created",
    Deployment.environment_id,
    Deployment.created_at.desc(),
    Deployment.id.desc(),
)
