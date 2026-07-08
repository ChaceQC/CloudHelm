"""create m4 agent orchestration tables

Revision ID: 20260708_0002
Revises: 20260708_0001
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260708_0002"
down_revision: str | None = "20260708_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 M4 Agent 编排、结构化输出和 DevelopmentPlan 数据结构。"""

    op.add_column("agent_runs", sa.Column("summary", sa.Text(), nullable=True, comment="结构化输出或失败摘要。"))
    op.add_column(
        "agent_runs",
        sa.Column("structured_output_type", sa.Text(), nullable=True, comment="结构化输出类型。"),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "structured_output_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="通过 schema 校验后的结构化输出 JSON。",
        ),
    )
    op.add_column("agent_runs", sa.Column("error_code", sa.Text(), nullable=True, comment="失败错误码。"))
    op.add_column("agent_runs", sa.Column("error_message", sa.Text(), nullable=True, comment="失败错误信息。"))

    op.create_table(
        "development_plans",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属任务 ID。"),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属项目 ID。"),
        sa.Column("technical_design_id", postgresql.UUID(as_uuid=True), nullable=False, comment="关联技术设计 ID。"),
        sa.Column("summary", sa.Text(), nullable=False, comment="开发计划摘要。"),
        sa.Column("steps_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("risks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("status", sa.Text(), nullable=False, comment="开发计划状态。"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, comment="记录唯一标识。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["technical_design_id"], ["technical_designs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_development_plans_task_status", "development_plans", ["task_id", "status"])
    op.create_index("ix_development_plans_project_id", "development_plans", ["project_id"])
    op.create_index("ix_development_plans_design", "development_plans", ["technical_design_id"])


def downgrade() -> None:
    """回滚 M4 Agent 编排扩展。"""

    op.drop_index("ix_development_plans_design", table_name="development_plans")
    op.drop_index("ix_development_plans_project_id", table_name="development_plans")
    op.drop_index("ix_development_plans_task_status", table_name="development_plans")
    op.drop_table("development_plans")
    op.drop_column("agent_runs", "error_message")
    op.drop_column("agent_runs", "error_code")
    op.drop_column("agent_runs", "structured_output_json")
    op.drop_column("agent_runs", "structured_output_type")
    op.drop_column("agent_runs", "summary")
