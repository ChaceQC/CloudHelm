"""create M7 CI run, deployment and service instance tables

Revision ID: 20260716_0009
Revises: 20260716_0008
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立 M7-2D CI 与远端部署权威数据底座。"""

    _extend_deployment_approval()
    _create_ci_runs()
    _create_deployments()
    _create_service_instances()


def downgrade() -> None:
    """按依赖逆序移除 M7-2D 数据结构。"""

    _drop_service_instances()
    _drop_deployments()
    _drop_ci_runs()
    _restore_deployment_approval()


def _extend_deployment_approval() -> None:
    """双向绑定 deployment resource、L3 风险与 AgentRun 发起者。"""

    op.create_check_constraint(
        "ck_approval_requests_deployment",
        "approval_requests",
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
    )
    op.create_check_constraint(
        "ck_approval_requests_m7_resource_action_group",
        "approval_requests",
        """
        action NOT IN (
          'approve_release_candidate',
          'approve_deployment'
        )
        OR resource_type IS NOT NULL
        """,
    )


def _create_ci_runs() -> None:
    """创建唯一 workflow dispatch 对应的 CI 权威记录。"""

    op.create_table(
        "ci_runs",
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
            comment="来源 PullRequestRecord。",
        ),
        sa.Column(
            "release_candidate_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="唯一 ReleaseCandidate。",
        ),
        sa.Column(
            "provider",
            sa.Text(),
            server_default="gitea",
            nullable=False,
            comment="M7 固定为 gitea。",
        ),
        sa.Column(
            "repository_external_id",
            sa.Text(),
            nullable=False,
            comment="Gitea repository 稳定外部 ID。",
        ),
        sa.Column(
            "external_run_id",
            sa.Text(),
            nullable=True,
            comment="Gitea run ID；dispatch 接受后可暂时为空。",
        ),
        sa.Column(
            "external_job_id",
            sa.Text(),
            nullable=True,
            comment="Gitea job ID。",
        ),
        sa.Column(
            "workflow_id",
            sa.Text(),
            nullable=False,
            comment="服务端受控 workflow 标识。",
        ),
        sa.Column(
            "workflow_revision",
            sa.Text(),
            nullable=False,
            comment="有界 opaque workflow revision。",
        ),
        sa.Column(
            "source_ref",
            sa.Text(),
            nullable=False,
            comment="完整受控 candidate ref。",
        ),
        sa.Column(
            "commit_sha",
            sa.Text(),
            nullable=False,
            comment="精确 40/64 位 commit SHA。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="triggered",
            nullable=False,
            comment="CI 生命周期状态。",
        ),
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=False,
            comment="Task 内 CI 创建幂等键。",
        ),
        sa.Column(
            "last_event_action",
            sa.Text(),
            nullable=True,
            comment="最后一次接受的 provider event action。",
        ),
        sa.Column(
            "last_event_status",
            sa.Text(),
            nullable=True,
            comment="最后一次接受的 provider event status。",
        ),
        sa.Column(
            "last_delivery_id",
            sa.Text(),
            nullable=True,
            comment="最后一次安全幂等 delivery 线索。",
        ),
        sa.Column(
            "provider_head_sha",
            sa.Text(),
            nullable=True,
            comment="provider 回报的 head SHA。",
        ),
        sa.Column(
            "provider_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="provider 记录的更新时间。",
        ),
        sa.Column(
            "artifact_manifest_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="通过 CI 的 manifest Artifact。",
        ),
        sa.Column(
            "image_index_digest",
            sa.Text(),
            nullable=True,
            comment="不可变 OCI image index digest。",
        ),
        sa.Column(
            "platform_manifest_digest",
            sa.Text(),
            nullable=True,
            comment="CloudHelm platform manifest digest。",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="CI 开始时间。",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="CI 终态时间。",
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
            name="ck_ci_runs_provider",
        ),
        sa.CheckConstraint(
            """
            status IN (
              'triggered',
              'running',
              'passed',
              'failed',
              'cancelled'
            )
            """,
            name="ck_ci_runs_status",
        ),
        sa.CheckConstraint(
            """
            length(btrim(repository_external_id)) BETWEEN 1 AND 255
            AND repository_external_id !~ '[[:cntrl:]]'
            """,
            name="ck_ci_runs_repository_identity",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            """
            length(btrim(workflow_id)) BETWEEN 1 AND 512
            AND workflow_id !~ '[[:cntrl:]]'
            """,
            name="ck_ci_runs_workflow_identity",
        ),
        sa.CheckConstraint(
            """
            length(btrim(workflow_revision)) BETWEEN 1 AND 255
            AND workflow_revision !~ '[[:cntrl:]]'
            """,
            name="ck_ci_runs_workflow_revision",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_ci_runs_commit_sha",
        ),
        sa.CheckConstraint(
            """
            provider_head_sha IS NULL
            OR (
              provider_head_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
              AND provider_head_sha = commit_sha
            )
            """,
            name="ck_ci_runs_provider_head_sha",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_ci_runs_idempotency_key",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
            ["release_candidate_id"],
            ["release_candidates.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_manifest_id"],
            ["artifacts.id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_candidate_id",
            name="uq_ci_runs_release_candidate",
        ),
        sa.UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_ci_runs_task_idempotency",
        ),
    )
    op.create_index(
        "ux_ci_runs_provider_repository_run",
        "ci_runs",
        ["provider", "repository_external_id", "external_run_id"],
        unique=True,
        postgresql_where=sa.text("external_run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ci_runs_task_created",
        "ci_runs",
        ["task_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_ci_runs_project_created",
        "ci_runs",
        ["project_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def _create_deployments() -> None:
    """创建受第二道审批约束的远端部署权威记录。"""

    op.create_table(
        "deployments",
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
            "environment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="目标 staging/demo Environment。",
        ),
        sa.Column(
            "remote_target_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="执行部署的 Linux RemoteTarget。",
        ),
        sa.Column(
            "ci_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="提供不可变制品的 CIRun。",
        ),
        sa.Column(
            "release_plan_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="不可变 ReleasePlan Artifact。",
        ),
        sa.Column(
            "commit_sha",
            sa.Text(),
            nullable=False,
            comment="精确 40/64 位 commit SHA。",
        ),
        sa.Column(
            "image_ref",
            sa.Text(),
            nullable=False,
            comment="包含不可变 digest 的 OCI image ref。",
        ),
        sa.Column(
            "image_digest",
            sa.Text(),
            nullable=False,
            comment="不可变 OCI image digest。",
        ),
        sa.Column(
            "platform_manifest_digest",
            sa.Text(),
            nullable=False,
            comment="CloudHelm platform manifest digest。",
        ),
        sa.Column(
            "release_version",
            sa.Text(),
            nullable=False,
            comment="Environment 内唯一发布版本。",
        ),
        sa.Column(
            "request_hash",
            sa.Text(),
            nullable=False,
            comment="deployment canonical request SHA-256。",
        ),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="第二道 L3 deployment Approval。",
        ),
        sa.Column(
            "remote_operation_id",
            sa.Text(),
            nullable=True,
            comment="Remote Agent 幂等 operation ID。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="planned",
            nullable=False,
            comment="部署生命周期状态。",
        ),
        sa.Column(
            "health_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="有界脱敏健康摘要。",
        ),
        sa.Column(
            "failure_code",
            sa.Text(),
            nullable=True,
            comment="稳定失败码。",
        ),
        sa.Column(
            "failure_summary",
            sa.Text(),
            nullable=True,
            comment="有界脱敏失败摘要。",
        ),
        sa.Column(
            "requested_by_actor",
            sa.Text(),
            nullable=False,
            comment="请求者兼容投影。",
        ),
        sa.Column(
            "approved_by_actor",
            sa.Text(),
            nullable=True,
            comment="审批者兼容投影。",
        ),
        sa.Column(
            "dispatched_by_agent_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="执行部署调度的 AgentRun。",
        ),
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=False,
            comment="Task 内部署幂等键。",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Remote Agent operation 开始时间。",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="部署终态时间。",
        ),
        sa.Column(
            "rollback_candidate_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="历史 Deployment 回滚候选。",
        ),
        sa.Column(
            "rollback_request_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="仅描述回滚请求的 Artifact。",
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
              'planned',
              'pending_approval',
              'queued',
              'deploying',
              'verifying',
              'healthy',
              'unhealthy',
              'failed',
              'rollback_requested',
              'cancelled'
            )
            """,
            name="ck_deployments_status",
        ),
        sa.CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_deployments_commit_sha",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            """
            image_digest ~ '^sha256:[0-9a-f]{64}$'
            AND platform_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
            """,
            name="ck_deployments_digests",
        ),
        sa.CheckConstraint(
            """
            length(btrim(release_version)) BETWEEN 1 AND 128
            AND release_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            """,
            name="ck_deployments_release_version",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_deployments_request_hash",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 180",
            name="ck_deployments_idempotency_key",
        ),
        sa.CheckConstraint(
            """
            health_summary_json IS NULL
            OR jsonb_typeof(health_summary_json)
              IS NOT DISTINCT FROM 'object'
            """,
            name="ck_deployments_health_summary_object",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
                'queued',
                'deploying',
                'verifying',
                'healthy',
                'unhealthy',
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            """
            status NOT IN ('healthy', 'unhealthy', 'rollback_requested')
            OR health_summary_json IS NOT NULL
            """,
            name="ck_deployments_health_lifecycle",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
        sa.CheckConstraint(
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
            ["environment_id"],
            ["environments.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["remote_target_id"],
            ["remote_targets.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["ci_run_id"],
            ["ci_runs.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["release_plan_artifact_id"],
            ["artifacts.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_requests.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["dispatched_by_agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_candidate_id"],
            ["deployments.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_request_artifact_id"],
            ["artifacts.id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_deployments_task_idempotency",
        ),
        sa.UniqueConstraint(
            "environment_id",
            "release_version",
            name="uq_deployments_environment_release_version",
        ),
    )
    op.create_index(
        "ux_deployments_approval",
        "deployments",
        ["approval_id"],
        unique=True,
        postgresql_where=sa.text("approval_id IS NOT NULL"),
    )
    op.create_index(
        "ux_deployments_remote_target_operation",
        "deployments",
        ["remote_target_id", "remote_operation_id"],
        unique=True,
        postgresql_where=sa.text("remote_operation_id IS NOT NULL"),
    )
    op.create_index(
        "ix_deployments_task_created",
        "deployments",
        ["task_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_deployments_project_created",
        "deployments",
        ["project_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_deployments_environment_created",
        "deployments",
        ["environment_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def _create_service_instances() -> None:
    """创建 Deployment 下的 Docker Compose 服务实例。"""

    op.create_table(
        "service_instances",
        sa.Column(
            "deployment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 Deployment。",
        ),
        sa.Column(
            "environment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 staging/demo Environment。",
        ),
        sa.Column(
            "remote_target_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="运行服务的 Linux RemoteTarget。",
        ),
        sa.Column(
            "service_name",
            sa.Text(),
            nullable=False,
            comment="受控 Compose service slug。",
        ),
        sa.Column(
            "compose_project",
            sa.Text(),
            nullable=False,
            comment="受控 Compose project slug。",
        ),
        sa.Column(
            "runtime_type",
            sa.Text(),
            server_default="docker_compose",
            nullable=False,
            comment="M7 固定为 docker_compose。",
        ),
        sa.Column(
            "runtime_ref",
            sa.Text(),
            nullable=True,
            comment="Remote Agent 返回的容器或服务引用。",
        ),
        sa.Column(
            "image_digest",
            sa.Text(),
            nullable=False,
            comment="不可变 OCI digest。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="starting",
            nullable=False,
            comment="服务生命周期状态。",
        ),
        sa.Column(
            "health_url",
            sa.Text(),
            nullable=True,
            comment="服务端 profile 派生的健康 URL。",
        ),
        sa.Column(
            "health_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="最近一次结构化脱敏健康结果。",
        ),
        sa.Column(
            "last_health_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次健康检查时间。",
        ),
        sa.Column(
            "last_error_code",
            sa.Text(),
            nullable=True,
            comment="稳定、脱敏的最近错误码。",
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
            "runtime_type = 'docker_compose'",
            name="ck_service_instances_runtime_type",
        ),
        sa.CheckConstraint(
            """
            status IN (
              'starting',
              'running',
              'healthy',
              'unhealthy',
              'stopped',
              'failed'
            )
            """,
            name="ck_service_instances_status",
        ),
        sa.CheckConstraint(
            """
            service_name ~ '^[a-z0-9][a-z0-9_-]{0,62}$'
            AND compose_project ~ '^[a-z0-9][a-z0-9_-]{0,62}$'
            """,
            name="ck_service_instances_slugs",
        ),
        sa.CheckConstraint(
            """
            runtime_ref IS NULL
            OR (
              length(btrim(runtime_ref)) BETWEEN 1 AND 255
              AND runtime_ref !~ '[[:cntrl:]]'
            )
            """,
            name="ck_service_instances_runtime_ref",
        ),
        sa.CheckConstraint(
            "image_digest ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_service_instances_image_digest",
        ),
        sa.CheckConstraint(
            """
            health_url IS NULL
            OR (
              length(health_url) BETWEEN 1 AND 2048
              AND health_url ~ '^https?://[^[:space:]]+$'
              AND health_url !~ '[[:cntrl:]]'
              AND health_url ~ '^https?://[^/[:space:]?#]+'
              AND health_url !~ '^https?://[^/?#]*@'
              AND position(chr(92) IN health_url) = 0
              AND position('#' IN health_url) = 0
            )
            """,
            name="ck_service_instances_health_url",
        ),
        sa.CheckConstraint(
            """
            health_result_json IS NULL
            OR jsonb_typeof(health_result_json)
              IS NOT DISTINCT FROM 'object'
            """,
            name="ck_service_instances_health_result_object",
        ),
        sa.CheckConstraint(
            """
            health_result_json IS NULL
            OR jsonb_typeof(health_result_json) IS DISTINCT FROM 'object'
            OR (
              jsonb_array_length(
                jsonb_path_query_array(
                  health_result_json,
                  '$.keyvalue()'
                )
              ) <= 32
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.keyvalue() ? (!(@.key like_regex "^[a-z][a-z0-9_]{0,63}$"))'
              )
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.keyvalue() ? (@.key like_regex "(^|_)(token|tokens|secret|secrets|credential|credentials|password|passwords|cookie|cookies|authorization|raw_logs|stdout|stderr|log|logs)(_|$)" flag "i")'
              )
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.* ? (@.type() == "array" || @.type() == "object")'
              )
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.* ? (@.type() == "string" && @ like_regex "^.{255}.{255}.{3}" flag "s")'
              )
            )
            """,
            name="ck_service_instances_health_result_safe",
        ),
        sa.CheckConstraint(
            """
            (health_result_json IS NULL) = (last_health_check_at IS NULL)
            AND (
              status NOT IN ('healthy', 'unhealthy')
              OR (
                health_result_json IS NOT NULL
                AND last_health_check_at IS NOT NULL
              )
            )
            """,
            name="ck_service_instances_health_lifecycle",
        ),
        sa.CheckConstraint(
            """
            (
              last_error_code IS NULL
              OR last_error_code ~ '^[a-z][a-z0-9_]{0,127}$'
            )
            AND (status <> 'failed' OR last_error_code IS NOT NULL)
            """,
            name="ck_service_instances_error_code",
        ),
        sa.CheckConstraint(
            """
            updated_at >= created_at
            AND (
              last_health_check_at IS NULL
              OR last_health_check_at >= created_at
            )
            """,
            name="ck_service_instances_time_order",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"],
            ["deployments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["remote_target_id"],
            ["remote_targets.id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deployment_id",
            "service_name",
            name="uq_service_instances_deployment_service",
        ),
    )
    op.create_index(
        "ix_service_instances_environment_status_created",
        "service_instances",
        [
            "environment_id",
            "status",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_service_instances_remote_target_status_created",
        "service_instances",
        [
            "remote_target_id",
            "status",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )


def _drop_service_instances() -> None:
    """移除 ServiceInstance 表及显式索引。"""

    op.drop_index(
        "ix_service_instances_remote_target_status_created",
        table_name="service_instances",
    )
    op.drop_index(
        "ix_service_instances_environment_status_created",
        table_name="service_instances",
    )
    op.drop_table("service_instances")


def _drop_deployments() -> None:
    """移除 Deployment 表及显式索引。"""

    op.drop_index(
        "ix_deployments_environment_created",
        table_name="deployments",
    )
    op.drop_index(
        "ix_deployments_project_created",
        table_name="deployments",
    )
    op.drop_index(
        "ix_deployments_task_created",
        table_name="deployments",
    )
    op.drop_index(
        "ux_deployments_remote_target_operation",
        table_name="deployments",
    )
    op.drop_index(
        "ux_deployments_approval",
        table_name="deployments",
    )
    op.drop_table("deployments")


def _drop_ci_runs() -> None:
    """移除 CIRun 表及显式索引。"""

    op.drop_index("ix_ci_runs_project_created", table_name="ci_runs")
    op.drop_index("ix_ci_runs_task_created", table_name="ci_runs")
    op.drop_index(
        "ux_ci_runs_provider_repository_run",
        table_name="ci_runs",
    )
    op.drop_table("ci_runs")


def _restore_deployment_approval() -> None:
    """移除 M7-2D deployment Approval 组合门禁。"""

    op.drop_constraint(
        "ck_approval_requests_m7_resource_action_group",
        "approval_requests",
        type_="check",
        if_exists=True,
    )
    op.drop_constraint(
        "ck_approval_requests_deployment",
        "approval_requests",
        type_="check",
    )
