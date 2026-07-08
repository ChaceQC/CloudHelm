"""create core m2 tables

Revision ID: 20260708_0001
Revises:
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260708_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 M2 数据模型、API 与事件底座所需基础表。"""

    op.create_table(
        "projects",
        sa.Column("name", sa.Text(), nullable=False, comment="项目显示名称。"),
        sa.Column("repo_url", sa.Text(), nullable=False, comment="仓库地址。"),
        sa.Column("default_branch", sa.Text(), nullable=False, comment="默认工作分支。"),
        sa.Column("provider", sa.Text(), nullable=False, comment="仓库提供方。"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tasks",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属项目 ID。"),
        sa.Column("title", sa.Text(), nullable=False, comment="任务标题。"),
        sa.Column("description", sa.Text(), nullable=False, comment="任务描述。"),
        sa.Column("source_type", sa.Text(), nullable=False, comment="任务来源。"),
        sa.Column("source_ref", sa.Text(), nullable=True, comment="来源引用。"),
        sa.Column("status", sa.Text(), nullable=False, comment="任务状态。"),
        sa.Column("risk_level", sa.Text(), nullable=False, comment="任务整体风险等级。"),
        sa.Column("current_phase", sa.Text(), nullable=False, comment="Orchestrator 当前阶段。"),
        sa.Column("created_by", sa.Text(), nullable=False, comment="创建人或组件。"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_project_status", "tasks", ["project_id", "status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])

    op.create_table(
        "agent_runs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属任务 ID。"),
        sa.Column("agent_type", sa.Text(), nullable=False, comment="Agent 类型。"),
        sa.Column("status", sa.Text(), nullable=False, comment="运行状态。"),
        sa.Column("model_name", sa.Text(), nullable=True, comment="使用的模型名称。"),
        sa.Column("prompt_hash", sa.Text(), nullable=True, comment="Prompt 版本或哈希。"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_task_status", "agent_runs", ["task_id", "status"])
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"])

    op.create_table(
        "requirement_specs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属任务 ID。"),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属项目 ID。"),
        sa.Column("source_type", sa.Text(), nullable=False, comment="需求来源类型。"),
        sa.Column("raw_input", sa.Text(), nullable=False, comment="原始需求输入。"),
        sa.Column("user_story", sa.Text(), nullable=True, comment="用户故事描述。"),
        sa.Column("constraints_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("acceptance_criteria_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("status", sa.Text(), nullable=False, comment="需求规格状态。"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirement_specs_task_status", "requirement_specs", ["task_id", "status"])
    op.create_index("ix_requirement_specs_project_id", "requirement_specs", ["project_id"])

    op.create_table(
        "approval_requests",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属任务 ID。"),
        sa.Column("action", sa.Text(), nullable=False, comment="申请执行的动作。"),
        sa.Column("risk_level", sa.Text(), nullable=False, comment="动作风险等级。"),
        sa.Column("reason", sa.Text(), nullable=False, comment="申请原因。"),
        sa.Column("status", sa.Text(), nullable=False, comment="审批状态。"),
        sa.Column("requested_by_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True, comment="审批决策人。"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.ForeignKeyConstraint(["requested_by_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approval_requests_task_status", "approval_requests", ["task_id", "status"])
    op.create_index("ix_approval_requests_created_at", "approval_requests", ["created_at"])

    op.create_table(
        "technical_designs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属任务 ID。"),
        sa.Column("requirement_spec_id", postgresql.UUID(as_uuid=True), nullable=False, comment="关联需求规格 ID。"),
        sa.Column("design_type", sa.Text(), nullable=False, comment="设计类型。"),
        sa.Column("content_markdown", sa.Text(), nullable=False, comment="设计正文。"),
        sa.Column("openapi_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("db_schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mermaid_diagram", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.Text(), nullable=False, comment="设计风险等级。"),
        sa.Column("status", sa.Text(), nullable=False, comment="设计审批状态。"),
        sa.Column("created_by_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requirement_spec_id"], ["requirement_specs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_technical_designs_task_status", "technical_designs", ["task_id", "status"])
    op.create_index("ix_technical_designs_requirement", "technical_designs", ["requirement_spec_id"])

    op.create_table(
        "tool_calls",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属任务 ID。"),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False, comment="工具名称。"),
        sa.Column("risk_level", sa.Text(), nullable=False, comment="工具风险等级。"),
        sa.Column("arguments_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, comment="工具调用状态。"),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_calls_task_status", "tool_calls", ["task_id", "status"])
    op.create_index("ix_tool_calls_agent_run_id", "tool_calls", ["agent_run_id"])
    op.create_index("ix_tool_calls_started_at", "tool_calls", ["started_at"])

    op.create_table(
        "event_logs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True, comment="事件所属任务。"),
        sa.Column("event_type", sa.Text(), nullable=False, comment="事件类型。"),
        sa.Column("actor_type", sa.Text(), nullable=False, comment="触发者类型。"),
        sa.Column("actor_id", sa.Text(), nullable=True, comment="触发者标识。"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_logs_task_created_at", "event_logs", ["task_id", "created_at"])
    op.create_index("ix_event_logs_event_type", "event_logs", ["event_type"])


def downgrade() -> None:
    """回滚 M2 基础表。"""

    op.drop_index("ix_event_logs_event_type", table_name="event_logs")
    op.drop_index("ix_event_logs_task_created_at", table_name="event_logs")
    op.drop_table("event_logs")
    op.drop_index("ix_tool_calls_started_at", table_name="tool_calls")
    op.drop_index("ix_tool_calls_agent_run_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_task_status", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_technical_designs_requirement", table_name="technical_designs")
    op.drop_index("ix_technical_designs_task_status", table_name="technical_designs")
    op.drop_table("technical_designs")
    op.drop_index("ix_approval_requests_created_at", table_name="approval_requests")
    op.drop_index("ix_approval_requests_task_status", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_requirement_specs_project_id", table_name="requirement_specs")
    op.drop_index("ix_requirement_specs_task_status", table_name="requirement_specs")
    op.drop_table("requirement_specs")
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_task_status", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_index("ix_tasks_project_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("projects")
