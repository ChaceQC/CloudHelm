"""M7 RemoteTarget、machine credential 与 replay ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
    utc_now,
)


class RemoteTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """由服务端 profile 注册的远端 Linux Remote Agent 目标。"""

    __tablename__ = "remote_targets"
    __table_args__ = (
        CheckConstraint(
            "target_type = 'linux_remote_agent'",
            name="ck_remote_targets_type",
        ),
        CheckConstraint(
            "status IN ('offline', 'online', 'degraded', 'disabled')",
            name="ck_remote_targets_status",
        ),
        CheckConstraint(
            "jsonb_typeof(capabilities_json) = 'array'",
            name="ck_remote_targets_capabilities_array",
        ),
        CheckConstraint(
            "tls_fingerprint ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_remote_targets_tls_fingerprint",
        ),
        UniqueConstraint(
            "environment_id",
            "agent_id",
            name="uq_remote_targets_environment_agent",
        ),
        Index(
            "ix_remote_targets_environment_status_created",
            "environment_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_remote_targets_last_heartbeat",
            "last_heartbeat_at",
        ),
    )

    environment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属 Environment ID。",
    )
    display_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="控制台展示名称。",
    )
    target_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="linux_remote_agent",
        comment="M7 固定为 linux_remote_agent。",
    )
    agent_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Remote Agent 稳定身份。",
    )
    agent_endpoint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端受控 HTTPS endpoint；API 仅返回脱敏展示值。",
    )
    credential_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="目标 credential 集合引用；API 不返回。",
    )
    tls_fingerprint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Remote Agent TLS 证书指纹。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="offline",
        comment="Remote Agent 在线状态。",
    )
    agent_version: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="最近一次心跳上报的 Agent 版本。",
    )
    capabilities_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="最近一次心跳上报的 capability 数组。",
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次已认证心跳的服务端接收时间。",
    )
    last_error_code: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="最近一次 Remote Agent 错误码。",
    )
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次 heartbeat 类 EventLog 写入时间。",
    )
    last_status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次 online/offline/degraded/disabled 状态变化时间。",
    )


class RemoteAgentCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """RemoteTarget machine credential 元数据。

    数据库只保存 credential ref 和 secret fingerprint，真实 HMAC secret
    始终从服务端 `SecretStr` 映射读取。
    """

    __tablename__ = "remote_agent_credentials"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(scopes_json) = 'array'",
            name="ck_remote_agent_credentials_scopes_array",
        ),
        CheckConstraint(
            "secret_fingerprint ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_remote_agent_credentials_secret_fingerprint",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > active_from",
            name="ck_remote_agent_credentials_expiry",
        ),
        UniqueConstraint(
            "target_id",
            "key_id",
            name="uq_remote_agent_credentials_target_key",
        ),
        Index(
            "ix_remote_agent_credentials_target_agent",
            "target_id",
            "agent_id",
        ),
        Index(
            "ix_remote_agent_credentials_expiry",
            "expires_at",
        ),
    )

    target_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("remote_targets.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属 RemoteTarget ID。",
    )
    agent_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="该密钥绑定的 Remote Agent 身份。",
    )
    key_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="支持新旧 key 重叠轮换的稳定标识。",
    )
    credential_ref: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="服务端 SecretStr 映射引用；API 不返回。",
    )
    scopes_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="machine API scope 数组。",
    )
    secret_fingerprint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="HMAC secret 的 sha256 指纹。",
    )
    active_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="密钥开始生效时间。",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="密钥过期时间。",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="密钥撤销时间。",
    )


class RemoteAgentReplayNonce(UUIDPrimaryKeyMixin, Base):
    """已认证 machine 请求的持久化 replay identity。"""

    __tablename__ = "remote_agent_replay_nonces"
    __table_args__ = (
        CheckConstraint(
            "nonce_hash ~ '^[0-9a-f]{64}$'",
            name="ck_remote_agent_replay_nonces_hash",
        ),
        CheckConstraint(
            "expires_at > request_timestamp",
            name="ck_remote_agent_replay_nonces_expiry",
        ),
        UniqueConstraint(
            "credential_id",
            "nonce_hash",
            name="uq_remote_agent_replay_nonces_credential_hash",
        ),
        Index(
            "ix_remote_agent_replay_nonces_expires",
            "expires_at",
        ),
    )

    credential_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("remote_agent_credentials.id", ondelete="CASCADE"),
        nullable=False,
        comment="认证该请求的 credential ID。",
    )
    nonce_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="原始 nonce 的 sha256 小写十六进制哈希。",
    )
    request_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="签名请求头携带的 UTC 时间。",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="replay identity 可清理时间。",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="nonce 持久化时间。",
    )
