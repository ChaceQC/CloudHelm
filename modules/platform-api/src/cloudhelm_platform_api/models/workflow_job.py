"""M7 durable WorkflowJob ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class WorkflowJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """PostgreSQL 权威的 durable workflow 业务任务。

    Redis/Celery 消息只携带本表 `id`。claim、lease、heartbeat、retry、
    enqueue compensation 与 terminal 结果都以本表为准，避免 broker 成为
    不可审计的业务状态源。
    """

    __tablename__ = "workflow_jobs"
    __table_args__ = (
        CheckConstraint(
            """
            job_type = 'release_candidate_reconcile'
            AND resource_type = 'release_candidate'
            AND side_effect_class = 'none'
            """,
            name="ck_workflow_jobs_m7_2_handler",
        ),
        CheckConstraint(
            """
            status IN (
              'pending',
              'claimed',
              'running',
              'succeeded',
              'failed',
              'cancel_requested',
              'cancelled',
              'recovery_required'
            )
            """,
            name="ck_workflow_jobs_status",
        ),
        CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_workflow_jobs_request_hash",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_workflow_jobs_idempotency_key",
        ),
        CheckConstraint(
            "attempt >= 0 AND max_attempts >= 1 AND attempt <= max_attempts",
            name="ck_workflow_jobs_attempts",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_workflow_jobs_payload_object",
        ),
        CheckConstraint(
            "result_json IS NULL OR jsonb_typeof(result_json) = 'object'",
            name="ck_workflow_jobs_result_object",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_workflow_jobs_worker_lease_pair",
        ),
        CheckConstraint(
            """
            (dispatch_lease_owner IS NULL)
            = (dispatch_lease_expires_at IS NULL)
            """,
            name="ck_workflow_jobs_dispatch_lease_pair",
        ),
        CheckConstraint(
            "dispatch_lease_owner IS NULL OR status = 'pending'",
            name="ck_workflow_jobs_dispatch_lease_status",
        ),
        CheckConstraint(
            """
            next_retry_at IS NULL
            OR (
              status = 'pending'
              AND next_enqueue_at IS NOT NULL
              AND next_enqueue_at >= next_retry_at
            )
            """,
            name="ck_workflow_jobs_retry_enqueue",
        ),
        CheckConstraint(
            "enqueue_attempt >= 0",
            name="ck_workflow_jobs_enqueue_attempt",
        ),
        CheckConstraint(
            """
            (
              status = 'pending'
              AND attempt < max_attempts
              AND lease_owner IS NULL
              AND heartbeat_at IS NULL
              AND finished_at IS NULL
              AND next_enqueue_at IS NOT NULL
            )
            OR (
              status = 'claimed'
              AND lease_owner IS NOT NULL
              AND heartbeat_at IS NOT NULL
              AND finished_at IS NULL
              AND next_retry_at IS NULL
              AND next_enqueue_at IS NULL
              AND dispatch_lease_owner IS NULL
            )
            OR (
              status IN ('running', 'cancel_requested')
              AND lease_owner IS NOT NULL
              AND heartbeat_at IS NOT NULL
              AND started_at IS NOT NULL
              AND finished_at IS NULL
              AND next_retry_at IS NULL
              AND next_enqueue_at IS NULL
              AND dispatch_lease_owner IS NULL
            )
            OR (
              status IN ('succeeded', 'failed', 'cancelled')
              AND lease_owner IS NULL
              AND finished_at IS NOT NULL
              AND next_retry_at IS NULL
              AND next_enqueue_at IS NULL
              AND dispatch_lease_owner IS NULL
            )
            OR (
              status = 'recovery_required'
              AND lease_owner IS NULL
              AND finished_at IS NULL
              AND next_retry_at IS NULL
              AND next_enqueue_at IS NULL
              AND dispatch_lease_owner IS NULL
            )
            """,
            name="ck_workflow_jobs_lifecycle",
        ),
        CheckConstraint(
            """
            (status <> 'cancel_requested' OR cancel_requested_at IS NOT NULL)
            AND (status <> 'cancelled' OR cancel_requested_at IS NOT NULL)
            AND (
              cancel_requested_at IS NULL
              OR status IN (
                'cancel_requested',
                'succeeded',
                'failed',
                'cancelled',
                'recovery_required'
              )
            )
            """,
            name="ck_workflow_jobs_cancel",
        ),
        CheckConstraint(
            """
            (
              status <> 'succeeded'
              OR (result_json IS NOT NULL AND error_code IS NULL)
            )
            AND (
              status NOT IN ('failed', 'cancelled', 'recovery_required')
              OR error_code IS NOT NULL
            )
            """,
            name="ck_workflow_jobs_result_semantics",
        ),
        CheckConstraint(
            """
            updated_at >= created_at
            AND (started_at IS NULL OR started_at >= created_at)
            AND (
              finished_at IS NULL
              OR finished_at >= COALESCE(started_at, created_at)
            )
            AND (heartbeat_at IS NULL OR heartbeat_at >= created_at)
            AND (
              lease_expires_at IS NULL
              OR (
                heartbeat_at IS NOT NULL
                AND lease_expires_at > heartbeat_at
              )
            )
            AND (
              cancel_requested_at IS NULL
              OR cancel_requested_at >= created_at
            )
            AND (
              last_enqueued_at IS NULL
              OR last_enqueued_at >= created_at
            )
            """,
            name="ck_workflow_jobs_time_order",
        ),
        UniqueConstraint(
            "task_id",
            "job_type",
            "idempotency_key",
            name="uq_workflow_jobs_task_type_idempotency",
        ),
        Index(
            "ux_workflow_jobs_blocking_resource",
            "job_type",
            "resource_type",
            "resource_id",
            unique=True,
            postgresql_where=text(
                """
                status IN (
                  'pending',
                  'claimed',
                  'running',
                  'cancel_requested',
                  'recovery_required'
                )
                """
            ),
        ),
        Index(
            "ix_workflow_jobs_status_lease",
            "status",
            "lease_expires_at",
            postgresql_where=text(
                "status IN ('claimed', 'running', 'cancel_requested')"
            ),
        ),
        Index(
            "ix_workflow_jobs_due_enqueue",
            "next_enqueue_at",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_workflow_jobs_due_retry",
            "next_retry_at",
            "id",
            postgresql_where=text(
                "status = 'pending' AND next_retry_at IS NOT NULL"
            ),
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    job_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端 handler registry 中的 job 类型。",
    )
    resource_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="job 绑定的领域资源类型。",
    )
    resource_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        comment="job 绑定的领域资源 ID。",
    )
    side_effect_class: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="由 handler registry 固定派生的副作用分类。",
    )
    request_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="job request canonical JSON 的稳定 SHA-256。",
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="任务与 job 类型内的幂等键。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
        comment="durable workflow 状态。",
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="成功 claim 的累计次数。",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
        comment="业务执行最大 claim 次数。",
    )
    lease_owner: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="当前 worker lease owner。",
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="当前 worker lease 过期时间。",
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次 worker lease 心跳时间。",
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="业务重试最早时间。",
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="取消请求时间。",
    )
    dispatch_lease_owner: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="当前 dispatcher reserve owner。",
    )
    dispatch_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="当前 dispatcher reserve lease 过期时间。",
    )
    next_enqueue_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
        comment="broker 下一次补投时间。",
    )
    last_enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次 broker publish 成功时间。",
    )
    enqueue_attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="dispatcher reserve/publish 尝试次数。",
    )
    last_enqueue_error_code: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="最近一次 broker publish 稳定错误码。",
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment="由 job 类型定义的严格 payload。",
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="由 job 类型定义的严格 result。",
    )
    error_code: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="稳定业务错误码。",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="首次进入 running 的时间。",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="terminal 完成时间。",
    )


Index(
    "ix_workflow_jobs_task_created",
    WorkflowJob.task_id,
    WorkflowJob.created_at.desc(),
)
Index(
    "ix_workflow_jobs_resource_created",
    WorkflowJob.resource_type,
    WorkflowJob.resource_id,
    WorkflowJob.created_at.desc(),
)
