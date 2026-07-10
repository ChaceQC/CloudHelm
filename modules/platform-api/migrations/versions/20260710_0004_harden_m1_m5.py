"""harden m1-m5 audit persistence and metadata

Revision ID: 20260710_0004
Revises: 20260708_0003
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0004"
down_revision: str | None = "20260708_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLUMN_COMMENTS: dict[tuple[str, str], tuple[str | None, str]] = {
    ("projects", "provider"): ("仓库提供方。", "仓库提供方，例如 github、gitea 或 local。"),
    ("projects", "created_at"): (None, "记录创建时间。"),
    ("projects", "updated_at"): (None, "记录最近更新时间。"),
    ("tasks", "source_type"): ("任务来源。", "任务来源，例如 manual、issue 或 alert。"),
    ("tasks", "source_ref"): ("来源引用。", "来源引用，例如 issue URL。"),
    ("tasks", "created_at"): (None, "记录创建时间。"),
    ("tasks", "updated_at"): (None, "记录最近更新时间。"),
    ("agent_runs", "cost_usd"): (None, "本次运行估算成本。"),
    ("agent_runs", "started_at"): (None, "运行开始时间。"),
    ("agent_runs", "finished_at"): (None, "运行结束时间。"),
    ("event_logs", "task_id"): ("事件所属任务。", "事件所属任务；ProjectCreated 可为空。"),
    ("event_logs", "payload"): (None, "事件载荷。"),
    ("event_logs", "created_at"): (None, "事件创建时间。"),
    ("requirement_specs", "project_id"): ("所属项目 ID。", "冗余项目 ID，便于按项目检索需求。"),
    ("requirement_specs", "constraints_json"): (None, "约束条件 JSON 数组。"),
    ("requirement_specs", "acceptance_criteria_json"): (None, "验收标准 JSON 数组。"),
    ("requirement_specs", "version"): (None, "需求规格版本号。"),
    ("requirement_specs", "created_at"): (None, "记录创建时间。"),
    ("requirement_specs", "updated_at"): (None, "记录最近更新时间。"),
    ("approval_requests", "requested_by_agent_run_id"): (None, "发起审批的 AgentRun。"),
    ("approval_requests", "decided_at"): (None, "审批决策时间。"),
    ("approval_requests", "created_at"): (None, "审批创建时间。"),
    ("technical_designs", "openapi_json"): (None, "OpenAPI 草案 JSON。"),
    ("technical_designs", "db_schema_json"): (None, "数据库 schema 草案 JSON。"),
    ("technical_designs", "mermaid_diagram"): (None, "Mermaid 图。"),
    ("technical_designs", "risk_level"): ("设计风险等级。", "设计涉及的最高风险等级。"),
    ("technical_designs", "created_by_agent_run_id"): (None, "创建该设计的 AgentRun；M2 可为空。"),
    ("technical_designs", "version"): (None, "技术设计版本号。"),
    ("technical_designs", "created_at"): (None, "记录创建时间。"),
    ("technical_designs", "updated_at"): (None, "记录最近更新时间。"),
    ("development_plans", "project_id"): ("所属项目 ID。", "冗余项目 ID，便于控制台按项目查询。"),
    ("development_plans", "steps_json"): (None, "开发任务图步骤 JSON 数组。"),
    ("development_plans", "risks_json"): (None, "开发计划风险 JSON 数组。"),
    ("development_plans", "version"): (None, "开发计划版本。"),
    ("development_plans", "created_by_agent_run_id"): (None, "创建该计划的 Planner AgentRun。"),
    ("development_plans", "created_at"): (None, "记录创建时间。"),
    ("development_plans", "updated_at"): (None, "记录最近更新时间。"),
    ("tool_calls", "agent_run_id"): (None, "触发该工具调用的 AgentRun。"),
    ("tool_calls", "arguments_json"): (None, "脱敏后的工具参数 JSON；文件正文只保留长度和 hash。"),
    ("tool_calls", "audit_json"): (None, "Tool Gateway 生成的参数 hash、主体、风险、幂等键和终态审计字段。"),
    ("tool_calls", "result_json"): (None, "工具结果 JSON。"),
    ("tool_calls", "approval_id"): (None, "关联审批请求 ID。"),
    ("tool_calls", "started_at"): (None, "调用开始时间。"),
    ("tool_calls", "finished_at"): (None, "调用结束时间。"),
}


def _set_column_comment(table: str, column: str, comment: str | None) -> None:
    """使用静态标识符设置 PostgreSQL column comment。"""

    literal = "NULL" if comment is None else "'" + comment.replace("'", "''") + "'"
    op.execute(f'COMMENT ON COLUMN "{table}"."{column}" IS {literal}')


def upgrade() -> None:
    """新增 ToolCall 审计 JSON，并同步 ORM metadata 注释。"""

    op.add_column(
        "tool_calls",
        sa.Column(
            "audit_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Tool Gateway 生成的参数 hash、主体、风险、幂等键和终态审计字段。",
        ),
    )
    for (table, column), (_, current_comment) in COLUMN_COMMENTS.items():
        _set_column_comment(table, column, current_comment)


def downgrade() -> None:
    """移除审计字段并恢复迁移前数据库注释。"""

    for (table, column), (previous_comment, _) in COLUMN_COMMENTS.items():
        if column != "audit_json":
            _set_column_comment(table, column, previous_comment)
    op.drop_column("tool_calls", "audit_json")
