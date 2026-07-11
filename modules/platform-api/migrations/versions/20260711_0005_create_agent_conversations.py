"""create Codex-style root and subagent conversations

Revision ID: 20260711_0005
Revises: 20260710_0004
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_0005"
down_revision: str | None = "20260710_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 Task root/subagent 会话和 AgentRun 缓存证据。"""

    op.create_table(
        "agent_conversations",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属 Task；普通角色共享同一 root conversation。",
        ),
        sa.Column(
            "parent_conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="显式 subagent 的父会话；root 为 NULL。",
        ),
        sa.Column(
            "spawned_by_agent_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="显式创建该 subagent 的父 AgentRun。",
        ),
        sa.Column(
            "source_type",
            sa.Text(),
            server_default="root",
            nullable=False,
            comment="会话来源：root 或 subagent。",
        ),
        sa.Column(
            "agent_role",
            sa.Text(),
            nullable=True,
            comment="subagent 角色；root 不绑定 Requirement/Architect 等普通角色。",
        ),
        sa.Column("nickname", sa.Text(), nullable=True, comment="控制台展示用子 Agent 名称。"),
        sa.Column(
            "objective",
            sa.Text(),
            nullable=True,
            comment="显式 spawn 指定的唯一子目标；root 为 NULL。",
        ),
        sa.Column(
            "depth",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="从 root 开始的 subagent 深度。",
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="active",
            nullable=False,
            comment="会话生命周期状态。",
        ),
        sa.Column(
            "fork_mode",
            sa.Text(),
            nullable=True,
            comment="子会话上下文模式：fresh 或 full_history。",
        ),
        sa.Column("provider_name", sa.Text(), nullable=False, comment="Provider 名称。"),
        sa.Column(
            "model_name",
            sa.Text(),
            nullable=True,
            comment="模型名称；本地规则 Provider 也记录其稳定版本名。",
        ),
        sa.Column(
            "prompt_cache_key",
            sa.Text(),
            nullable=False,
            comment="供应商 Prompt Cache 路由键。",
        ),
        sa.Column(
            "items_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="可重放的完整 ResponseItem 数组，包含 encrypted reasoning 和工具项。",
        ),
        sa.Column(
            "turn_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="已成功提交的模型 turn 数。",
        ),
        sa.Column(
            "last_response_id",
            sa.Text(),
            nullable=True,
            comment="最近一次供应商 Responses response id。",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="子会话完成、失败或取消时间。",
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
            "source_type IN ('root', 'subagent')",
            name="ck_agent_conversations_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'failed', 'cancelled')",
            name="ck_agent_conversations_status",
        ),
        sa.CheckConstraint(
            "fork_mode IS NULL OR fork_mode IN ('fresh', 'full_history')",
            name="ck_agent_conversations_fork_mode",
        ),
        sa.CheckConstraint(
            "("
            "source_type = 'root' AND parent_conversation_id IS NULL "
            "AND spawned_by_agent_run_id IS NULL AND agent_role IS NULL "
            "AND objective IS NULL AND fork_mode IS NULL AND depth = 0"
            ") OR ("
            "source_type = 'subagent' AND parent_conversation_id IS NOT NULL "
            "AND spawned_by_agent_run_id IS NOT NULL AND agent_role IS NOT NULL "
            "AND objective IS NOT NULL AND fork_mode IS NOT NULL AND depth > 0"
            ")",
            name="ck_agent_conversations_source_fields",
        ),
        sa.CheckConstraint("depth >= 0", name="ck_agent_conversations_depth"),
        sa.ForeignKeyConstraint(
            ["parent_conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["spawned_by_agent_run_id"],
            ["agent_runs.id"],
            name="fk_agent_conversations_spawned_by_agent_run_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_cache_key", name="uq_agent_conversations_prompt_cache_key"),
    )
    op.create_index(
        "ux_agent_conversations_task_root",
        "agent_conversations",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("source_type = 'root'"),
    )
    op.create_index(
        "ix_agent_conversations_parent_status",
        "agent_conversations",
        ["parent_conversation_id", "status"],
    )
    op.create_index(
        "ix_agent_conversations_task_status",
        "agent_conversations",
        ["task_id", "status"],
    )

    op.add_column(
        "agent_runs",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="本次运行所属 root 或显式 subagent conversation。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "conversation_turn",
            sa.Integer(),
            nullable=True,
            comment="本次成功输出提交后的 conversation turn。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "cached_input_tokens",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="供应商 usage 返回的真实缓存输入 token。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "provider_request_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="本次 AgentRun 内已完成并返回 usage 的模型请求次数。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "provider_requests",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="每次已完成供应商请求的原始 token/cache usage 证据。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "provider_response_id",
            sa.Text(),
            nullable=True,
            comment="最后一次供应商 Responses response id。",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "prompt_cache_key",
            sa.Text(),
            nullable=True,
            comment="供应商 Prompt Cache 路由键。",
        ),
    )
    op.create_foreign_key(
        "fk_agent_runs_conversation_id",
        "agent_runs",
        "agent_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_runs_conversation_turn",
        "agent_runs",
        ["conversation_id", "conversation_turn"],
    )


def downgrade() -> None:
    """移除 Task conversation 和 AgentRun 缓存证据。"""

    op.drop_index("ix_agent_runs_conversation_turn", table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_conversation_id",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "prompt_cache_key")
    op.drop_column("agent_runs", "provider_response_id")
    op.drop_column("agent_runs", "provider_requests")
    op.drop_column("agent_runs", "provider_request_count")
    op.drop_column("agent_runs", "cached_input_tokens")
    op.drop_column("agent_runs", "conversation_turn")
    op.drop_column("agent_runs", "conversation_id")
    op.drop_index(
        "ix_agent_conversations_task_status",
        table_name="agent_conversations",
    )
    op.drop_index(
        "ix_agent_conversations_parent_status",
        table_name="agent_conversations",
    )
    op.drop_index(
        "ux_agent_conversations_task_root",
        table_name="agent_conversations",
    )
    op.drop_table("agent_conversations")
