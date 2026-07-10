"""Alembic 迁移验证。"""

from sqlalchemy import text

from cloudhelm_platform_api.db.session import get_engine


def test_alembic_migration_creates_core_tables() -> None:
    """验证 M2 核心表由 Alembic 迁移创建。"""

    expected = {
        "projects",
        "tasks",
        "requirement_specs",
        "technical_designs",
        "agent_runs",
        "tool_calls",
        "approval_requests",
        "event_logs",
    }
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
        )
        actual = {row.table_name for row in rows}

    assert expected.issubset(actual)


def test_tool_calls_contains_persisted_audit_json_column() -> None:
    """M5 二次审计字段必须由 Alembic migration 创建。"""

    with get_engine().connect() as connection:
        columns = {
            row.column_name
            for row in connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'tool_calls'
                    """
                )
            )
        }

    assert "audit_json" in columns
