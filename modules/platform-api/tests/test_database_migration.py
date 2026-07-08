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
