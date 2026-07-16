"""create M7 repository binding, release candidate and workflow job tables

Revision ID: 20260716_0008
Revises: 20260715_0007
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0008"
down_revision: str | None = "20260715_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 M7-2 候选发布与 durable workflow 持久化结构。"""

    _extend_approval_requests()
    _create_project_repository_bindings()
    _create_release_candidates()
    _create_workflow_jobs()


def downgrade() -> None:
    """按依赖逆序移除 M7-2 数据结构并恢复 ApprovalRequest。"""

    _drop_workflow_jobs()
    _drop_release_candidates()
    _drop_project_repository_bindings()
    _restore_approval_requests()


def _extend_approval_requests() -> None:
    """扩展资源审批身份、freshness 与单次消费字段。"""

    op.add_column(
        "approval_requests",
        sa.Column(
            "resource_type",
            sa.Text(),
            nullable=True,
            comment="审批绑定的领域资源类型。",
        ),
    )
    op.add_column(
        "approval_requests",
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="审批绑定的领域资源 ID。",
        ),
    )
    op.add_column(
        "approval_requests",
        sa.Column(
            "request_hash",
            sa.Text(),
            nullable=True,
            comment="审批请求 canonical JSON 的稳定 SHA-256。",
        ),
    )
    op.add_column(
        "approval_requests",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="资源审批有效期截止时间。",
        ),
    )
    op.add_column(
        "approval_requests",
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="批准后首次受控副作用消费时间。",
        ),
    )
    op.create_check_constraint(
        "ck_approval_requests_status",
        "approval_requests",
        "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_approval_requests_resource_group",
        "approval_requests",
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
    )
    op.create_check_constraint(
        "ck_approval_requests_request_hash",
        "approval_requests",
        "request_hash IS NULL OR request_hash ~ '^sha256:[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_approval_requests_decision",
        "approval_requests",
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
    )
    op.create_check_constraint(
        "ck_approval_requests_release_candidate",
        "approval_requests",
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
    )
    op.create_check_constraint(
        "ck_approval_requests_expiry",
        "approval_requests",
        "expires_at IS NULL OR expires_at > created_at",
    )
    op.create_check_constraint(
        "ck_approval_requests_decision_before_expiry",
        "approval_requests",
        """
        resource_type IS NULL
        OR status NOT IN ('approved', 'rejected')
        OR (
          decided_at IS NOT NULL
          AND expires_at IS NOT NULL
          AND decided_at < expires_at
        )
        """,
    )
    op.create_check_constraint(
        "ck_approval_requests_consumed",
        "approval_requests",
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
    )
    op.create_check_constraint(
        "ck_approval_requests_time_order",
        "approval_requests",
        "decided_at IS NULL OR decided_at >= created_at",
    )
    op.create_index(
        "ux_approval_requests_resource_action",
        "approval_requests",
        ["resource_type", "resource_id", "action"],
        unique=True,
        postgresql_where=sa.text("resource_type IS NOT NULL"),
    )
    op.create_index(
        "ix_approval_requests_resource_status",
        "approval_requests",
        ["resource_type", "resource_id", "status"],
        postgresql_where=sa.text("resource_type IS NOT NULL"),
    )
    op.create_index(
        "ix_approval_requests_pending_expiry",
        "approval_requests",
        ["expires_at", "id"],
        postgresql_where=sa.text(
            "status = 'pending' AND expires_at IS NOT NULL"
        ),
    )


def _create_project_repository_bindings() -> None:
    """创建由服务端 profile 物化的项目仓库绑定表。"""

    op.create_table(
        "project_repository_bindings",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属项目 ID。",
        ),
        sa.Column(
            "provider",
            sa.Text(),
            server_default="gitea",
            nullable=False,
            comment="M7 固定为 gitea。",
        ),
        sa.Column(
            "profile_key",
            sa.Text(),
            nullable=False,
            comment="服务端 repository profile key。",
        ),
        sa.Column(
            "repository_external_id",
            sa.Text(),
            nullable=False,
            comment="Gitea repository 稳定外部 ID。",
        ),
        sa.Column(
            "repository_owner",
            sa.Text(),
            nullable=False,
            comment="仓库 owner。",
        ),
        sa.Column(
            "repository_name",
            sa.Text(),
            nullable=False,
            comment="仓库名称。",
        ),
        sa.Column(
            "clone_url",
            sa.Text(),
            nullable=False,
            comment="服务端受控 HTTPS clone URL；API 不返回。",
        ),
        sa.Column(
            "default_branch",
            sa.Text(),
            nullable=False,
            comment="远端仓库默认分支。",
        ),
        sa.Column(
            "credential_ref",
            sa.Text(),
            nullable=False,
            comment="服务端 credential 引用；API 不返回。",
        ),
        sa.Column(
            "workflow_id",
            sa.Text(),
            nullable=False,
            comment="受控 Gitea workflow 文件标识。",
        ),
        sa.Column(
            "release_ref_prefix",
            sa.Text(),
            nullable=False,
            comment="候选发布 ref 的完整受控前缀。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="active",
            nullable=False,
            comment="绑定状态。",
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
            "provider = 'gitea'",
            name="ck_project_repository_bindings_provider",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_project_repository_bindings_status",
        ),
        sa.CheckConstraint(
            "profile_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'",
            name="ck_project_repository_bindings_profile_key",
        ),
        sa.CheckConstraint(
            """
            length(btrim(repository_external_id)) BETWEEN 1 AND 255
            AND length(btrim(repository_owner)) BETWEEN 1 AND 255
            AND length(btrim(repository_name)) BETWEEN 1 AND 255
            """,
            name="ck_project_repository_bindings_identity",
        ),
        sa.CheckConstraint(
            """
            clone_url ~ '^https://[^[:space:]]+$'
            AND clone_url !~ '^https://[^/]*@'
            """,
            name="ck_project_repository_bindings_clone_url",
        ),
        sa.CheckConstraint(
            """
            length(btrim(default_branch)) BETWEEN 1 AND 255
            AND length(btrim(credential_ref)) BETWEEN 1 AND 512
            AND length(btrim(workflow_id)) BETWEEN 1 AND 512
            """,
            name="ck_project_repository_bindings_config",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_project_repository_bindings_time_order",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            name="uq_project_repository_bindings_project",
        ),
        sa.UniqueConstraint(
            "provider",
            "repository_external_id",
            name="uq_project_repository_bindings_external",
        ),
    )
    op.create_index(
        "ux_project_repository_bindings_owner_name",
        "project_repository_bindings",
        [
            "provider",
            sa.text("lower(repository_owner)"),
            sa.text("lower(repository_name)"),
        ],
        unique=True,
    )
    op.create_index(
        "ix_project_repository_bindings_status_updated",
        "project_repository_bindings",
        ["status", sa.text("updated_at DESC")],
    )


def _create_release_candidates() -> None:
    """创建不可变 PR/snapshot 身份对应的候选发布记录。"""

    op.create_table(
        "release_candidates",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属任务 ID。",
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属项目 ID。",
        ),
        sa.Column(
            "pull_request_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="候选来源 M6 PullRequestRecord。",
        ),
        sa.Column(
            "repository_binding_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="候选使用的仓库绑定。",
        ),
        sa.Column(
            "binding_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="不含 secret 的八字段仓库绑定快照。",
        ),
        sa.Column(
            "binding_snapshot_sha256",
            sa.Text(),
            nullable=False,
            comment="覆盖内部绑定配置的稳定 SHA-256。",
        ),
        sa.Column(
            "commit_sha",
            sa.Text(),
            nullable=False,
            comment="候选对应完整 commit SHA。",
        ),
        sa.Column(
            "target_ref",
            sa.Text(),
            nullable=False,
            comment="服务端生成的完整候选发布 ref。",
        ),
        sa.Column(
            "request_hash",
            sa.Text(),
            nullable=False,
            comment="Candidate request canonical JSON 的稳定 SHA-256。",
        ),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="第一道 L2 release candidate 审批。",
        ),
        sa.Column(
            "remote_verified_sha",
            sa.Text(),
            nullable=True,
            comment="远端 ref 发布后回读确认的 commit SHA。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="pending_approval",
            nullable=False,
            comment="候选发布状态。",
        ),
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=False,
            comment="任务内候选发布幂等键。",
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="第一道审批通过时间。",
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="远端候选 ref 发布完成时间。",
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "binding_snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_release_candidates_snapshot_hash",
        ),
        sa.CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_release_candidates_commit_sha",
        ),
        sa.CheckConstraint(
            """
            remote_verified_sha IS NULL
            OR remote_verified_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
            """,
            name="ck_release_candidates_remote_sha",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_release_candidates_request_hash",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_release_candidates_idempotency_key",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pull_request_record_id"],
            ["pull_request_records.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["repository_binding_id"],
            ["project_repository_bindings.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_requests.id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_release_candidates_task_idempotency",
        ),
        sa.UniqueConstraint(
            "repository_binding_id",
            "target_ref",
            name="uq_release_candidates_binding_ref",
        ),
        sa.UniqueConstraint(
            "pull_request_record_id",
            "binding_snapshot_sha256",
            name="uq_release_candidates_pr_snapshot",
        ),
    )
    op.create_index(
        "ux_release_candidates_approval",
        "release_candidates",
        ["approval_id"],
        unique=True,
        postgresql_where=sa.text("approval_id IS NOT NULL"),
    )
    op.create_index(
        "ux_release_candidates_task_active",
        "release_candidates",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_approval', 'approved')"
        ),
    )
    op.create_index(
        "ix_release_candidates_task_status_created",
        "release_candidates",
        ["task_id", "status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_release_candidates_project_created",
        "release_candidates",
        ["project_id", sa.text("created_at DESC")],
    )


def _create_workflow_jobs() -> None:
    """创建 PostgreSQL 权威的 durable WorkflowJob 表。"""

    op.create_table(
        "workflow_jobs",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属任务 ID。",
        ),
        sa.Column(
            "job_type",
            sa.Text(),
            nullable=False,
            comment="服务端 handler registry 中的 job 类型。",
        ),
        sa.Column(
            "resource_type",
            sa.Text(),
            nullable=False,
            comment="job 绑定的领域资源类型。",
        ),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="job 绑定的领域资源 ID。",
        ),
        sa.Column(
            "side_effect_class",
            sa.Text(),
            nullable=False,
            comment="由 handler registry 固定派生的副作用分类。",
        ),
        sa.Column(
            "request_hash",
            sa.Text(),
            nullable=False,
            comment="job request canonical JSON 的稳定 SHA-256。",
        ),
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=False,
            comment="任务与 job 类型内的幂等键。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="pending",
            nullable=False,
            comment="durable workflow 状态。",
        ),
        sa.Column(
            "attempt",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="成功 claim 的累计次数。",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
            comment="业务执行最大 claim 次数。",
        ),
        sa.Column(
            "lease_owner",
            sa.Text(),
            nullable=True,
            comment="当前 worker lease owner。",
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="当前 worker lease 过期时间。",
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次 worker lease 心跳时间。",
        ),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="业务重试最早时间。",
        ),
        sa.Column(
            "cancel_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="取消请求时间。",
        ),
        sa.Column(
            "dispatch_lease_owner",
            sa.Text(),
            nullable=True,
            comment="当前 dispatcher reserve owner。",
        ),
        sa.Column(
            "dispatch_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="当前 dispatcher reserve lease 过期时间。",
        ),
        sa.Column(
            "next_enqueue_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
            comment="broker 下一次补投时间。",
        ),
        sa.Column(
            "last_enqueued_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次 broker publish 成功时间。",
        ),
        sa.Column(
            "enqueue_attempt",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="dispatcher reserve/publish 尝试次数。",
        ),
        sa.Column(
            "last_enqueue_error_code",
            sa.Text(),
            nullable=True,
            comment="最近一次 broker publish 稳定错误码。",
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="由 job 类型定义的严格 payload。",
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="由 job 类型定义的严格 result。",
        ),
        sa.Column(
            "error_code",
            sa.Text(),
            nullable=True,
            comment="稳定业务错误码。",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="首次进入 running 的时间。",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="terminal 完成时间。",
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
            """
            job_type = 'release_candidate_reconcile'
            AND resource_type = 'release_candidate'
            AND side_effect_class = 'none'
            """,
            name="ck_workflow_jobs_m7_2_handler",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_workflow_jobs_request_hash",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_workflow_jobs_idempotency_key",
        ),
        sa.CheckConstraint(
            "attempt >= 0 AND max_attempts >= 1 AND attempt <= max_attempts",
            name="ck_workflow_jobs_attempts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_workflow_jobs_payload_object",
        ),
        sa.CheckConstraint(
            "result_json IS NULL OR jsonb_typeof(result_json) = 'object'",
            name="ck_workflow_jobs_result_object",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_workflow_jobs_worker_lease_pair",
        ),
        sa.CheckConstraint(
            """
            (dispatch_lease_owner IS NULL)
            = (dispatch_lease_expires_at IS NULL)
            """,
            name="ck_workflow_jobs_dispatch_lease_pair",
        ),
        sa.CheckConstraint(
            "dispatch_lease_owner IS NULL OR status = 'pending'",
            name="ck_workflow_jobs_dispatch_lease_status",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "enqueue_attempt >= 0",
            name="ck_workflow_jobs_enqueue_attempt",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "job_type",
            "idempotency_key",
            name="uq_workflow_jobs_task_type_idempotency",
        ),
    )
    op.create_index(
        "ux_workflow_jobs_blocking_resource",
        "workflow_jobs",
        ["job_type", "resource_type", "resource_id"],
        unique=True,
        postgresql_where=sa.text(
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
    )
    op.create_index(
        "ix_workflow_jobs_task_created",
        "workflow_jobs",
        ["task_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_workflow_jobs_resource_created",
        "workflow_jobs",
        ["resource_type", "resource_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_workflow_jobs_status_lease",
        "workflow_jobs",
        ["status", "lease_expires_at"],
        postgresql_where=sa.text(
            "status IN ('claimed', 'running', 'cancel_requested')"
        ),
    )
    op.create_index(
        "ix_workflow_jobs_due_enqueue",
        "workflow_jobs",
        ["next_enqueue_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_workflow_jobs_due_retry",
        "workflow_jobs",
        ["next_retry_at", "id"],
        postgresql_where=sa.text(
            "status = 'pending' AND next_retry_at IS NOT NULL"
        ),
    )


def _drop_workflow_jobs() -> None:
    """移除 WorkflowJob 表及其索引。"""

    op.drop_index("ix_workflow_jobs_due_retry", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_due_enqueue", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_status_lease", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_resource_created", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_task_created", table_name="workflow_jobs")
    op.drop_index("ux_workflow_jobs_blocking_resource", table_name="workflow_jobs")
    op.drop_table("workflow_jobs")


def _drop_release_candidates() -> None:
    """移除 ReleaseCandidate 表及其索引。"""

    op.drop_index(
        "ix_release_candidates_project_created",
        table_name="release_candidates",
    )
    op.drop_index(
        "ix_release_candidates_task_status_created",
        table_name="release_candidates",
    )
    op.drop_index(
        "ux_release_candidates_task_active",
        table_name="release_candidates",
    )
    op.drop_index(
        "ux_release_candidates_approval",
        table_name="release_candidates",
    )
    op.drop_table("release_candidates")


def _drop_project_repository_bindings() -> None:
    """移除 ProjectRepositoryBinding 表及其索引。"""

    op.drop_index(
        "ix_project_repository_bindings_status_updated",
        table_name="project_repository_bindings",
    )
    op.drop_index(
        "ux_project_repository_bindings_owner_name",
        table_name="project_repository_bindings",
    )
    op.drop_table("project_repository_bindings")


def _restore_approval_requests() -> None:
    """恢复 M7-2 前的通用 ApprovalRequest 表结构。"""

    op.drop_index(
        "ix_approval_requests_pending_expiry",
        table_name="approval_requests",
    )
    op.drop_index(
        "ix_approval_requests_resource_status",
        table_name="approval_requests",
    )
    op.drop_index(
        "ux_approval_requests_resource_action",
        table_name="approval_requests",
    )
    for constraint_name in (
        "ck_approval_requests_time_order",
        "ck_approval_requests_consumed",
        "ck_approval_requests_decision_before_expiry",
        "ck_approval_requests_expiry",
        "ck_approval_requests_release_candidate",
        "ck_approval_requests_decision",
        "ck_approval_requests_request_hash",
        "ck_approval_requests_resource_group",
        "ck_approval_requests_status",
    ):
        op.drop_constraint(
            constraint_name,
            "approval_requests",
            type_="check",
        )
    op.drop_column("approval_requests", "consumed_at")
    op.drop_column("approval_requests", "expires_at")
    op.drop_column("approval_requests", "request_hash")
    op.drop_column("approval_requests", "resource_id")
    op.drop_column("approval_requests", "resource_type")
