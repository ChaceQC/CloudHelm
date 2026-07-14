"""M6 Artifact ORM 模型。"""

from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Artifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """受控本地产物元数据。

    文件内容由 Artifact service 写入配置的 artifact root；数据库只保存相对
    storage key、hash、大小和结构化摘要。API DTO 不暴露 storage key。
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "producer_type IN ('agent', 'tool', 'system')",
            name="ck_artifacts_producer_type",
        ),
        CheckConstraint(
            "("
            "producer_type = 'agent' AND agent_run_id IS NOT NULL "
            "AND tool_call_id IS NULL"
            ") OR ("
            "producer_type = 'tool' AND tool_call_id IS NOT NULL "
            "AND agent_run_id IS NULL"
            ") OR ("
            "producer_type = 'system' AND agent_run_id IS NULL "
            "AND tool_call_id IS NULL"
            ")",
            name="ck_artifacts_producer_reference",
        ),
        CheckConstraint(
            "status IN ('available', 'invalidated', 'missing')",
            name="ck_artifacts_status",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_artifacts_size_non_negative"),
        CheckConstraint(
            "sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_artifacts_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata_json) = 'object'",
            name="ck_artifacts_metadata_object",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_artifacts_task_idempotency",
        ),
        UniqueConstraint("storage_key", name="uq_artifacts_storage_key"),
        Index(
            "ix_artifacts_task_type_created",
            "task_id",
            "artifact_type",
            "created_at",
        ),
        Index(
            "ix_artifacts_task_status_created",
            "task_id",
            "status",
            "created_at",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        comment="生产该产物的 AgentRun。",
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tool_calls.id", ondelete="CASCADE"),
        comment="生产或收集该产物的 ToolCall。",
    )
    producer_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="产物生产者类型：agent、tool 或 system。",
    )
    artifact_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="产物类型，例如 diff_patch、test_report 或 security_report。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="available",
        comment="产物可用状态。",
    )
    display_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="控制台展示名称，不包含本机绝对路径。",
    )
    media_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="产物 MIME 类型。",
    )
    storage_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="相对 artifact root 的内部存储键；API 不直接返回。",
    )
    sha256: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="带 sha256: 前缀的内容哈希。",
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="产物字节数。",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="面向控制台的脱敏摘要。",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="产物结构化元数据，不保存本机绝对路径。",
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="任务内产物幂等键。",
    )
