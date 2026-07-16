"""ApprovalRequest ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    """人工审批请求。

    ApprovalRequest 是需求、设计、开发计划、M7 资源动作及 L3/L4 工具动作的
    审计基础。审批决策只改变受控状态；通用高风险工具不会在审批 HTTP 事务内
    自动补执行。
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="ck_approval_requests_status",
        ),
        CheckConstraint(
            """
            (
              resource_type IS NULL
              AND resource_id IS NULL
              AND request_hash IS NULL
              AND expires_at IS NULL
              AND consumed_at IS NULL
            )
            OR (
              resource_type IS NOT NULL
              AND resource_id IS NOT NULL
              AND request_hash IS NOT NULL
              AND expires_at IS NOT NULL
            )
            """,
            name="ck_approval_requests_resource_group",
        ),
        CheckConstraint(
            "request_hash IS NULL OR request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_approval_requests_request_hash",
        ),
        CheckConstraint(
            """
            (
              status = 'pending'
              AND decided_by IS NULL
              AND decided_at IS NULL
            )
            OR (
              status IN ('approved', 'rejected', 'expired', 'cancelled')
              AND decided_by IS NOT NULL
              AND decided_at IS NOT NULL
            )
            """,
            name="ck_approval_requests_decision",
        ),
        CheckConstraint(
            """
            (
              action = 'approve_release_candidate'
              AND resource_type = 'release_candidate'
              AND risk_level = 'L2'
              AND requested_by_agent_run_id IS NOT NULL
            )
            OR (
              action <> 'approve_release_candidate'
              AND resource_type IS DISTINCT FROM 'release_candidate'
            )
            """,
            name="ck_approval_requests_release_candidate",
        ),
        CheckConstraint(
            """
            (
              action = 'approve_deployment'
              AND resource_type IS NOT NULL
              AND resource_type = 'deployment'
              AND risk_level = 'L3'
              AND requested_by_agent_run_id IS NOT NULL
            )
            OR (
              action <> 'approve_deployment'
              AND resource_type IS DISTINCT FROM 'deployment'
            )
            """,
            name="ck_approval_requests_deployment",
        ),
        CheckConstraint(
            """
            action NOT IN (
              'approve_release_candidate',
              'approve_deployment'
            )
            OR resource_type IS NOT NULL
            """,
            name="ck_approval_requests_m7_resource_action_group",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_approval_requests_expiry",
        ),
        CheckConstraint(
            """
            resource_type IS NULL
            OR status NOT IN ('approved', 'rejected')
            OR (
              decided_at IS NOT NULL
              AND expires_at IS NOT NULL
              AND decided_at < expires_at
            )
            """,
            name="ck_approval_requests_decision_before_expiry",
        ),
        CheckConstraint(
            """
            consumed_at IS NULL
            OR (
              resource_type IS NOT NULL
              AND status = 'approved'
              AND decided_at IS NOT NULL
              AND expires_at IS NOT NULL
              AND consumed_at >= decided_at
              AND consumed_at < expires_at
            )
            """,
            name="ck_approval_requests_consumed",
        ),
        CheckConstraint(
            "decided_at IS NULL OR decided_at >= created_at",
            name="ck_approval_requests_time_order",
        ),
        Index("ix_approval_requests_task_status", "task_id", "status"),
        Index("ix_approval_requests_created_at", "created_at"),
        Index(
            "ux_approval_requests_resource_action",
            "resource_type",
            "resource_id",
            "action",
            unique=True,
            postgresql_where=text("resource_type IS NOT NULL"),
        ),
        Index(
            "ix_approval_requests_resource_status",
            "resource_type",
            "resource_id",
            "status",
            postgresql_where=text("resource_type IS NOT NULL"),
        ),
        Index(
            "ix_approval_requests_pending_expiry",
            "expires_at",
            "id",
            postgresql_where=text(
                "status = 'pending' AND expires_at IS NOT NULL"
            ),
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    action: Mapped[str] = mapped_column(Text, nullable=False, comment="申请执行的动作。")
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, comment="动作风险等级。")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="申请原因。")
    resource_type: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="审批绑定的领域资源类型。",
    )
    resource_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        comment="审批绑定的领域资源 ID。",
    )
    request_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="审批请求 canonical JSON 的稳定 SHA-256。",
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, comment="审批状态。")
    requested_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="发起审批的 AgentRun。",
    )
    decided_by: Mapped[str | None] = mapped_column(Text, comment="审批决策人。")
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="审批决策时间。",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="资源审批有效期截止时间。",
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="批准后首次受控副作用消费时间。",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="审批创建时间。",
    )
