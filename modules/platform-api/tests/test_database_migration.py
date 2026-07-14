"""Alembic 迁移验证。"""

import pytest
from sqlalchemy import text

from conftest import ALLOW_SCHEMA_RESET_ENV, _prepare_test_database
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
        "development_plans",
        "artifacts",
        "pull_request_records",
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


def test_m6_migration_creates_workflow_and_provider_identity_columns() -> None:
    """M6 step claim、工具 call_id 和 conversation revision 必须由 migration 创建。"""

    expected_by_table = {
        "agent_runs": {"workflow_step", "attempt", "idempotency_key"},
        "tool_calls": {"provider_call_id", "provider_item_type"},
        "agent_conversations": {"revision"},
    }
    with get_engine().connect() as connection:
        for table_name, expected in expected_by_table.items():
            columns = {
                row.column_name
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            }
            assert expected.issubset(columns)


def test_m6_migration_creates_constraints_indexes_and_delete_rules() -> None:
    """M6 唯一约束、部分索引和审计证据删除规则必须落到 PostgreSQL。"""

    expected_constraints = {
        "ck_agent_conversations_revision",
        "ck_agent_runs_attempt_positive",
        "ck_agent_runs_workflow_identity",
        "ck_tool_calls_provider_identity",
        "ck_tool_calls_provider_item_type",
        "ck_artifacts_metadata_object",
        "ck_artifacts_producer_reference",
        "ck_artifacts_sha256",
        "ck_pull_request_records_local_url",
        "uq_artifacts_task_idempotency",
        "uq_artifacts_storage_key",
        "uq_pull_request_records_task_commit",
        "uq_pull_request_records_task_idempotency",
    }
    expected_partial_indexes = {
        "ux_agent_runs_task_active_workflow": (
            "workflow_step IS NOT NULL"
        ),
        "ux_agent_runs_task_idempotency": "idempotency_key IS NOT NULL",
        "ux_tool_calls_agent_provider_call": "provider_call_id IS NOT NULL",
    }
    expected_delete_rules = {
        ("artifacts", "artifacts_task_id_fkey"): "c",
        ("pull_request_records", "pull_request_records_task_id_fkey"): "c",
        (
            "pull_request_records",
            "pull_request_records_development_plan_id_fkey",
        ): "r",
        (
            "pull_request_records",
            "pull_request_records_diff_artifact_id_fkey",
        ): "r",
        (
            "pull_request_records",
            "pull_request_records_branch_tool_call_id_fkey",
        ): "n",
    }

    with get_engine().connect() as connection:
        constraints = {
            row.conname
            for row in connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE connamespace = 'public'::regnamespace
                    """
                )
            )
        }
        index_definitions = {
            row.indexname: row.indexdef
            for row in connection.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname IN (
                        'ux_agent_runs_task_active_workflow',
                        'ux_agent_runs_task_idempotency',
                        'ux_tool_calls_agent_provider_call'
                      )
                    """
                )
            )
        }
        delete_rules = {
            (row.table_name, row.constraint_name): row.confdeltype
            for row in connection.execute(
                text(
                    """
                    SELECT
                        relation.relname AS table_name,
                        constraint_record.conname AS constraint_name,
                        constraint_record.confdeltype
                    FROM pg_constraint AS constraint_record
                    JOIN pg_class AS relation
                      ON relation.oid = constraint_record.conrelid
                    WHERE constraint_record.contype = 'f'
                      AND constraint_record.connamespace = 'public'::regnamespace
                    """
                )
            )
        }

    assert expected_constraints.issubset(constraints)
    for index_name, predicate in expected_partial_indexes.items():
        assert predicate in index_definitions[index_name]
    for identity, delete_rule in expected_delete_rules.items():
        assert delete_rules[identity] == delete_rule


def test_test_database_guard_rejects_development_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试夹具不得把开发库当成可重建的测试数据库。"""

    monkeypatch.setenv(
        "CLOUDHELM_TEST_DATABASE_URL",
        (
            "postgresql+psycopg://cloudhelm:cloudhelm_dev@"
            "127.0.0.1:15432/cloudhelm"
        ),
    )
    monkeypatch.setenv(ALLOW_SCHEMA_RESET_ENV, "true")

    with pytest.raises(RuntimeError, match="test"):
        _prepare_test_database()


def test_explicit_test_database_requires_destructive_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式复用专用测试库时必须同时确认允许重建 schema。"""

    monkeypatch.setenv(
        "CLOUDHELM_TEST_DATABASE_URL",
        (
            "postgresql+psycopg://cloudhelm:cloudhelm_dev@"
            "127.0.0.1:15432/cloudhelm_test"
        ),
    )
    monkeypatch.delenv(ALLOW_SCHEMA_RESET_ENV, raising=False)

    with pytest.raises(RuntimeError, match=ALLOW_SCHEMA_RESET_ENV):
        _prepare_test_database()
