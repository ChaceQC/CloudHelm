"""create M6 local development artifacts and PR records

Revision ID: 20260714_0006
Revises: 20260711_0005
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0006"
down_revision: str | None = "20260711_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 M6 step identity、工具 call identity、Artifact 和本地 PR record。"""

    op.add_column(
        "agent_conversations",
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="会话任意历史变更的乐观并发版本。",
        ),
    )
    op.create_check_constraint(
        "ck_agent_conversations_revision",
        "agent_conversations",
        "revision >= 0",
    )

    op.add_column(
        "agent_runs",
        sa.Column(
            "workflow_step",
            sa.Text(),
            nullable=True,
            comment="M6 工作流步骤，例如 run_coder 或 run_tester。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=True,
            comment="同一任务工作流步骤的重试序号，从 1 开始。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=True,
            comment="任务内 Agent 步骤幂等键。",
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_attempt_positive",
        "agent_runs",
        "attempt IS NULL OR attempt > 0",
    )
    op.create_check_constraint(
        "ck_agent_runs_workflow_identity",
        "agent_runs",
        "("
        "workflow_step IS NULL AND attempt IS NULL AND idempotency_key IS NULL"
        ") OR ("
        "workflow_step IS NOT NULL AND attempt IS NOT NULL "
        "AND idempotency_key IS NOT NULL"
        ")",
    )
    op.create_index(
        "ix_agent_runs_task_workflow_attempt",
        "agent_runs",
        ["task_id", "workflow_step", "attempt"],
    )
    op.create_index(
        "ux_agent_runs_task_idempotency",
        "agent_runs",
        ["task_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ux_agent_runs_task_active_workflow",
        "agent_runs",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text(
            "workflow_step IS NOT NULL "
            "AND status IN ('pending', 'running')"
        ),
    )

    op.add_column(
        "tool_calls",
        sa.Column(
            "provider_call_id",
            sa.Text(),
            nullable=True,
            comment="供应商 function/custom tool call_id。",
        ),
    )
    op.add_column(
        "tool_calls",
        sa.Column(
            "provider_item_type",
            sa.Text(),
            nullable=True,
            comment="供应商调用项类型：function_call 或 custom_tool_call。",
        ),
    )
    op.create_check_constraint(
        "ck_tool_calls_provider_item_type",
        "tool_calls",
        "provider_item_type IS NULL "
        "OR provider_item_type IN ('function_call', 'custom_tool_call')",
    )
    op.create_check_constraint(
        "ck_tool_calls_provider_identity",
        "tool_calls",
        "("
        "provider_call_id IS NULL AND provider_item_type IS NULL"
        ") OR ("
        "provider_call_id IS NOT NULL AND provider_item_type IS NOT NULL "
        "AND agent_run_id IS NOT NULL"
        ")",
    )
    op.create_index(
        "ux_tool_calls_agent_provider_call",
        "tool_calls",
        ["agent_run_id", "provider_call_id"],
        unique=True,
        postgresql_where=sa.text("provider_call_id IS NOT NULL"),
    )

    op.create_table(
        "artifacts",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属任务 ID。",
        ),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="生产该产物的 AgentRun。",
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="生产或收集该产物的 ToolCall。",
        ),
        sa.Column(
            "producer_type",
            sa.Text(),
            nullable=False,
            comment="产物生产者类型：agent、tool 或 system。",
        ),
        sa.Column(
            "artifact_type",
            sa.Text(),
            nullable=False,
            comment="产物类型，例如 diff_patch、test_report 或 security_report。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="available",
            nullable=False,
            comment="产物可用状态。",
        ),
        sa.Column(
            "display_name",
            sa.Text(),
            nullable=False,
            comment="控制台展示名称，不包含本机绝对路径。",
        ),
        sa.Column(
            "media_type",
            sa.Text(),
            nullable=False,
            comment="产物 MIME 类型。",
        ),
        sa.Column(
            "storage_key",
            sa.Text(),
            nullable=False,
            comment="相对 artifact root 的内部存储键；API 不直接返回。",
        ),
        sa.Column(
            "sha256",
            sa.Text(),
            nullable=False,
            comment="带 sha256: 前缀的内容哈希。",
        ),
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            nullable=False,
            comment="产物字节数。",
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            comment="面向控制台的脱敏摘要。",
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="产物结构化元数据，不保存本机绝对路径。",
        ),
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=False,
            comment="任务内产物幂等键。",
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
            "producer_type IN ('agent', 'tool', 'system')",
            name="ck_artifacts_producer_type",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "status IN ('available', 'invalidated', 'missing')",
            name="ck_artifacts_status",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_artifacts_size_non_negative",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_artifacts_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata_json) = 'object'",
            name="ck_artifacts_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["tool_calls.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_key",
            name="uq_artifacts_storage_key",
        ),
        sa.UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_artifacts_task_idempotency",
        ),
    )
    op.create_index(
        "ix_artifacts_task_type_created",
        "artifacts",
        ["task_id", "artifact_type", "created_at"],
    )
    op.create_index(
        "ix_artifacts_task_status_created",
        "artifacts",
        ["task_id", "status", "created_at"],
    )

    op.create_table(
        "pull_request_records",
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
            "development_plan_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="本地开发闭环使用的已批准 DevelopmentPlan。",
        ),
        sa.Column(
            "created_by_agent_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="完成 commit 或 PR record 的 AgentRun。",
        ),
        sa.Column(
            "branch_tool_call_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="创建本地分支的 ToolCall。",
        ),
        sa.Column(
            "commit_tool_call_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="创建本地提交的 ToolCall。",
        ),
        sa.Column(
            "provider",
            sa.Text(),
            server_default="local",
            nullable=False,
            comment="PR 提供方；M6 使用 local。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="open",
            nullable=False,
            comment="PR record 状态。",
        ),
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
            comment="本地等价 PR 标题。",
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            comment="本地等价 PR 摘要。",
        ),
        sa.Column(
            "base_branch",
            sa.Text(),
            nullable=False,
            comment="基准分支。",
        ),
        sa.Column(
            "head_branch",
            sa.Text(),
            nullable=False,
            comment="开发分支。",
        ),
        sa.Column(
            "base_commit_sha",
            sa.Text(),
            nullable=False,
            comment="基准提交 SHA。",
        ),
        sa.Column(
            "commit_sha",
            sa.Text(),
            nullable=False,
            comment="M6 最终本地提交 SHA。",
        ),
        sa.Column(
            "changed_files_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="真实 changed files 数组。",
        ),
        sa.Column(
            "diff_stat_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="真实 diff stat 结构。",
        ),
        sa.Column(
            "diff_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="patch/diff Artifact。",
        ),
        sa.Column(
            "test_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="通过的 TestReport Artifact。",
        ),
        sa.Column(
            "review_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="通过的 ReviewReport Artifact。",
        ),
        sa.Column(
            "security_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="非阻断 SecurityReport Artifact。",
        ),
        sa.Column(
            "url",
            sa.Text(),
            nullable=True,
            comment="真实远端 PR URL；local provider 必须为空。",
        ),
        sa.Column(
            "idempotency_key",
            sa.Text(),
            nullable=False,
            comment="任务内 PR record 幂等键。",
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
            "provider IN ('local', 'github', 'gitea')",
            name="ck_pull_request_records_provider",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'superseded', 'closed')",
            name="ck_pull_request_records_status",
        ),
        sa.CheckConstraint(
            "base_branch <> head_branch",
            name="ck_pull_request_records_distinct_branches",
        ),
        sa.CheckConstraint(
            "base_commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_pull_request_records_base_commit_sha",
        ),
        sa.CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_pull_request_records_commit_sha",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changed_files_json) = 'array'",
            name="ck_pull_request_records_changed_files_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(diff_stat_json) = 'object'",
            name="ck_pull_request_records_diff_stat_object",
        ),
        sa.CheckConstraint(
            "provider <> 'local' OR url IS NULL",
            name="ck_pull_request_records_local_url",
        ),
        sa.ForeignKeyConstraint(
            ["branch_tool_call_id"],
            ["tool_calls.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["commit_tool_call_id"],
            ["tool_calls.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["development_plan_id"],
            ["development_plans.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["diff_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["security_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "commit_sha",
            name="uq_pull_request_records_task_commit",
        ),
        sa.UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_pull_request_records_task_idempotency",
        ),
    )
    op.create_index(
        "ix_pull_request_records_task_status_created",
        "pull_request_records",
        ["task_id", "status", "created_at"],
    )
    op.create_index(
        "ix_pull_request_records_project_created",
        "pull_request_records",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    """移除 M6 本地开发基础数据结构。"""

    op.drop_index(
        "ix_pull_request_records_project_created",
        table_name="pull_request_records",
    )
    op.drop_index(
        "ix_pull_request_records_task_status_created",
        table_name="pull_request_records",
    )
    op.drop_table("pull_request_records")

    op.drop_index(
        "ix_artifacts_task_status_created",
        table_name="artifacts",
    )
    op.drop_index(
        "ix_artifacts_task_type_created",
        table_name="artifacts",
    )
    op.drop_table("artifacts")

    op.drop_index(
        "ux_tool_calls_agent_provider_call",
        table_name="tool_calls",
    )
    op.drop_constraint(
        "ck_tool_calls_provider_identity",
        "tool_calls",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_calls_provider_item_type",
        "tool_calls",
        type_="check",
    )
    op.drop_column("tool_calls", "provider_item_type")
    op.drop_column("tool_calls", "provider_call_id")

    op.drop_index(
        "ux_agent_runs_task_active_workflow",
        table_name="agent_runs",
        if_exists=True,
    )
    op.drop_index(
        "ux_agent_runs_task_idempotency",
        table_name="agent_runs",
    )
    op.drop_index(
        "ix_agent_runs_task_workflow_attempt",
        table_name="agent_runs",
    )
    op.drop_constraint(
        "ck_agent_runs_workflow_identity",
        "agent_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_runs_attempt_positive",
        "agent_runs",
        type_="check",
    )
    op.drop_column("agent_runs", "idempotency_key")
    op.drop_column("agent_runs", "attempt")
    op.drop_column("agent_runs", "workflow_step")

    op.drop_constraint(
        "ck_agent_conversations_revision",
        "agent_conversations",
        type_="check",
    )
    op.drop_column("agent_conversations", "revision")
