"""create M7 environment, remote target and machine auth tables

Revision ID: 20260715_0007
Revises: 20260714_0006
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260715_0007"
down_revision: str | None = "20260714_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 M7 Environment、RemoteTarget 与 machine-auth 持久化底座。"""

    op.create_table(
        "environments",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属项目 ID。",
        ),
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            comment="项目内唯一环境名称。",
        ),
        sa.Column(
            "environment_type",
            sa.Text(),
            nullable=False,
            comment="M7 只允许 staging 或 demo。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="active",
            nullable=False,
            comment="环境状态。",
        ),
        sa.Column(
            "base_url",
            sa.Text(),
            nullable=False,
            comment="环境基础 URL；M7-1 仅用于标识和展示。",
        ),
        sa.Column(
            "env_profile_ref",
            sa.Text(),
            nullable=True,
            comment="受控远端 env profile 引用；API 不返回。",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="记录唯一标识。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录最近更新时间。",
        ),
        sa.CheckConstraint(
            "environment_type IN ('staging', 'demo')",
            name="ck_environments_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'degraded')",
            name="ck_environments_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "name",
            name="uq_environments_project_name",
        ),
    )
    op.create_index(
        "ix_environments_project_status_created",
        "environments",
        ["project_id", "status", "created_at"],
    )

    op.create_table(
        "remote_targets",
        sa.Column(
            "environment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 Environment ID。",
        ),
        sa.Column(
            "display_name",
            sa.Text(),
            nullable=False,
            comment="控制台展示名称。",
        ),
        sa.Column(
            "target_type",
            sa.Text(),
            server_default="linux_remote_agent",
            nullable=False,
            comment="M7 固定为 linux_remote_agent。",
        ),
        sa.Column(
            "agent_id",
            sa.Text(),
            nullable=False,
            comment="Remote Agent 稳定身份。",
        ),
        sa.Column(
            "agent_endpoint",
            sa.Text(),
            nullable=False,
            comment="服务端受控 HTTPS endpoint；API 仅返回脱敏展示值。",
        ),
        sa.Column(
            "credential_ref",
            sa.Text(),
            nullable=False,
            comment="目标 credential 集合引用；API 不返回。",
        ),
        sa.Column(
            "tls_fingerprint",
            sa.Text(),
            nullable=False,
            comment="Remote Agent TLS 证书指纹。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="offline",
            nullable=False,
            comment="Remote Agent 在线状态。",
        ),
        sa.Column(
            "agent_version",
            sa.Text(),
            nullable=True,
            comment="最近一次心跳上报的 Agent 版本。",
        ),
        sa.Column(
            "capabilities_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="最近一次心跳上报的 capability 数组。",
        ),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次已认证心跳的服务端接收时间。",
        ),
        sa.Column(
            "last_error_code",
            sa.Text(),
            nullable=True,
            comment="最近一次 Remote Agent 错误码。",
        ),
        sa.Column(
            "last_event_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次 heartbeat 类 EventLog 写入时间。",
        ),
        sa.Column(
            "last_status_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次 online/offline/degraded/disabled 状态变化时间。",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="记录唯一标识。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录最近更新时间。",
        ),
        sa.CheckConstraint(
            "target_type = 'linux_remote_agent'",
            name="ck_remote_targets_type",
        ),
        sa.CheckConstraint(
            "status IN ('offline', 'online', 'degraded', 'disabled')",
            name="ck_remote_targets_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capabilities_json) = 'array'",
            name="ck_remote_targets_capabilities_array",
        ),
        sa.CheckConstraint(
            "tls_fingerprint ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_remote_targets_tls_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "environment_id",
            "agent_id",
            name="uq_remote_targets_environment_agent",
        ),
    )
    op.create_index(
        "ix_remote_targets_environment_status_created",
        "remote_targets",
        ["environment_id", "status", "created_at"],
    )
    op.create_index(
        "ix_remote_targets_last_heartbeat",
        "remote_targets",
        ["last_heartbeat_at"],
    )

    op.create_table(
        "remote_agent_credentials",
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 RemoteTarget ID。",
        ),
        sa.Column(
            "agent_id",
            sa.Text(),
            nullable=False,
            comment="该密钥绑定的 Remote Agent 身份。",
        ),
        sa.Column(
            "key_id",
            sa.Text(),
            nullable=False,
            comment="支持新旧 key 重叠轮换的稳定标识。",
        ),
        sa.Column(
            "credential_ref",
            sa.Text(),
            nullable=False,
            comment="服务端 SecretStr 映射引用；API 不返回。",
        ),
        sa.Column(
            "scopes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="machine API scope 数组。",
        ),
        sa.Column(
            "secret_fingerprint",
            sa.Text(),
            nullable=False,
            comment="HMAC secret 的 sha256 指纹。",
        ),
        sa.Column(
            "active_from",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="密钥开始生效时间。",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="密钥过期时间。",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="密钥撤销时间。",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="记录唯一标识。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录最近更新时间。",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scopes_json) = 'array'",
            name="ck_remote_agent_credentials_scopes_array",
        ),
        sa.CheckConstraint(
            "secret_fingerprint ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_remote_agent_credentials_secret_fingerprint",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > active_from",
            name="ck_remote_agent_credentials_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["remote_targets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_id",
            "key_id",
            name="uq_remote_agent_credentials_target_key",
        ),
    )
    op.create_index(
        "ix_remote_agent_credentials_target_agent",
        "remote_agent_credentials",
        ["target_id", "agent_id"],
    )
    op.create_index(
        "ix_remote_agent_credentials_expiry",
        "remote_agent_credentials",
        ["expires_at"],
    )

    op.create_table(
        "remote_agent_replay_nonces",
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="认证该请求的 credential ID。",
        ),
        sa.Column(
            "nonce_hash",
            sa.Text(),
            nullable=False,
            comment="原始 nonce 的 sha256 小写十六进制哈希。",
        ),
        sa.Column(
            "request_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="签名请求头携带的 UTC 时间。",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="replay identity 可清理时间。",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="记录唯一标识。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="nonce 持久化时间。",
        ),
        sa.CheckConstraint(
            "nonce_hash ~ '^[0-9a-f]{64}$'",
            name="ck_remote_agent_replay_nonces_hash",
        ),
        sa.CheckConstraint(
            "expires_at > request_timestamp",
            name="ck_remote_agent_replay_nonces_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["remote_agent_credentials.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "credential_id",
            "nonce_hash",
            name="uq_remote_agent_replay_nonces_credential_hash",
        ),
    )
    op.create_index(
        "ix_remote_agent_replay_nonces_expires",
        "remote_agent_replay_nonces",
        ["expires_at"],
    )


def downgrade() -> None:
    """按外键依赖逆序移除 M7-1 数据结构。"""

    op.drop_index(
        "ix_remote_agent_replay_nonces_expires",
        table_name="remote_agent_replay_nonces",
    )
    op.drop_table("remote_agent_replay_nonces")

    op.drop_index(
        "ix_remote_agent_credentials_expiry",
        table_name="remote_agent_credentials",
    )
    op.drop_index(
        "ix_remote_agent_credentials_target_agent",
        table_name="remote_agent_credentials",
    )
    op.drop_table("remote_agent_credentials")

    op.drop_index(
        "ix_remote_targets_last_heartbeat",
        table_name="remote_targets",
    )
    op.drop_index(
        "ix_remote_targets_environment_status_created",
        table_name="remote_targets",
    )
    op.drop_table("remote_targets")

    op.drop_index(
        "ix_environments_project_status_created",
        table_name="environments",
    )
    op.drop_table("environments")
