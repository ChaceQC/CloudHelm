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
        "agent_conversations",
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


def test_agent_runs_contains_conversation_and_cache_evidence_columns() -> None:
    """v0.4.3 必须持久化真实 conversation 和供应商 cache usage。"""

    expected = {
        "conversation_id",
        "conversation_turn",
        "cached_input_tokens",
        "provider_request_count",
        "provider_requests",
        "provider_response_id",
        "prompt_cache_key",
    }
    with get_engine().connect() as connection:
        columns = {
            row.column_name
            for row in connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'agent_runs'
                    """
                )
            )
        }

    assert expected.issubset(columns)
