"""extend tool calls for m5 tool gateway

Revision ID: 20260708_0003
Revises: 20260708_0002
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260708_0003"
down_revision: str | None = "20260708_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 M5 Tool Gateway 增加幂等键、摘要和错误字段。"""

    op.add_column("tool_calls", sa.Column("idempotency_key", sa.Text(), nullable=True, comment="任务内幂等键。"))
    op.add_column("tool_calls", sa.Column("arguments_summary", sa.Text(), nullable=True, comment="脱敏参数摘要。"))
    op.add_column("tool_calls", sa.Column("result_summary", sa.Text(), nullable=True, comment="工具结果摘要。"))
    op.add_column("tool_calls", sa.Column("stdout_summary", sa.Text(), nullable=True, comment="stdout 截断摘要。"))
    op.add_column("tool_calls", sa.Column("stderr_summary", sa.Text(), nullable=True, comment="stderr 截断摘要。"))
    op.add_column("tool_calls", sa.Column("duration_ms", sa.Integer(), nullable=True, comment="工具调用耗时毫秒数。"))
    op.add_column("tool_calls", sa.Column("error_code", sa.Text(), nullable=True, comment="失败错误码。"))
    op.create_index(
        "ux_tool_calls_task_idempotency",
        "tool_calls",
        ["task_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """回滚 M5 ToolCall 字段扩展。"""

    op.drop_index("ux_tool_calls_task_idempotency", table_name="tool_calls")
    op.drop_column("tool_calls", "error_code")
    op.drop_column("tool_calls", "duration_ms")
    op.drop_column("tool_calls", "stderr_summary")
    op.drop_column("tool_calls", "stdout_summary")
    op.drop_column("tool_calls", "result_summary")
    op.drop_column("tool_calls", "arguments_summary")
    op.drop_column("tool_calls", "idempotency_key")
