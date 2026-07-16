"""Alembic 迁移验证。"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from conftest import ALLOW_SCHEMA_RESET_ENV, _prepare_test_database
from m7_release_job_fixture import (
    build_release_candidate,
    build_workflow_job,
    seed_m7_candidate_dependencies,
    valid_binding_snapshot,
)
from cloudhelm_platform_api.db.base import utc_now
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
        "environments",
        "remote_targets",
        "remote_agent_credentials",
        "remote_agent_replay_nonces",
        "project_repository_bindings",
        "release_candidates",
        "workflow_jobs",
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


def test_m7_environment_remote_target_migration_contract() -> None:
    """M7-1 表、约束、索引和级联删除规则必须由 migration 创建。"""

    expected_columns = {
        "environments": {
            "project_id",
            "name",
            "environment_type",
            "status",
            "base_url",
            "env_profile_ref",
        },
        "remote_targets": {
            "environment_id",
            "display_name",
            "target_type",
            "agent_id",
            "agent_endpoint",
            "credential_ref",
            "tls_fingerprint",
            "status",
            "agent_version",
            "capabilities_json",
            "last_heartbeat_at",
            "last_error_code",
            "last_event_at",
            "last_status_changed_at",
        },
        "remote_agent_credentials": {
            "target_id",
            "agent_id",
            "key_id",
            "credential_ref",
            "scopes_json",
            "secret_fingerprint",
            "active_from",
            "expires_at",
            "revoked_at",
        },
        "remote_agent_replay_nonces": {
            "credential_id",
            "nonce_hash",
            "request_timestamp",
            "expires_at",
            "created_at",
        },
    }
    expected_constraints = {
        "ck_environments_type",
        "ck_environments_status",
        "uq_environments_project_name",
        "ck_remote_targets_type",
        "ck_remote_targets_status",
        "ck_remote_targets_capabilities_array",
        "ck_remote_targets_tls_fingerprint",
        "uq_remote_targets_environment_agent",
        "ck_remote_agent_credentials_scopes_array",
        "ck_remote_agent_credentials_secret_fingerprint",
        "ck_remote_agent_credentials_expiry",
        "uq_remote_agent_credentials_target_key",
        "ck_remote_agent_replay_nonces_hash",
        "ck_remote_agent_replay_nonces_expiry",
        "uq_remote_agent_replay_nonces_credential_hash",
    }
    expected_indexes = {
        "ix_environments_project_status_created",
        "ix_remote_targets_environment_status_created",
        "ix_remote_targets_last_heartbeat",
        "ix_remote_agent_credentials_target_agent",
        "ix_remote_agent_credentials_expiry",
        "ix_remote_agent_replay_nonces_expires",
    }
    expected_delete_rules = {
        ("environments", "environments_project_id_fkey"): "c",
        ("remote_targets", "remote_targets_environment_id_fkey"): "c",
        (
            "remote_agent_credentials",
            "remote_agent_credentials_target_id_fkey",
        ): "c",
        (
            "remote_agent_replay_nonces",
            "remote_agent_replay_nonces_credential_id_fkey",
        ): "c",
    }

    with get_engine().connect() as connection:
        for table_name, expected in expected_columns.items():
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
        indexes = {
            row.indexname
            for row in connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
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
    assert expected_indexes.issubset(indexes)
    for identity, delete_rule in expected_delete_rules.items():
        assert delete_rules[identity] == delete_rule


def test_m7_release_job_migration_contract() -> None:
    """M7-2 表、Approval 扩展、部分索引和删除规则必须精确落库。"""

    expected_columns = {
        "approval_requests": {
            "resource_type",
            "resource_id",
            "request_hash",
            "expires_at",
            "consumed_at",
        },
        "project_repository_bindings": {
            "id",
            "project_id",
            "provider",
            "profile_key",
            "repository_external_id",
            "repository_owner",
            "repository_name",
            "clone_url",
            "default_branch",
            "credential_ref",
            "workflow_id",
            "release_ref_prefix",
            "status",
            "created_at",
            "updated_at",
        },
        "release_candidates": {
            "id",
            "task_id",
            "project_id",
            "pull_request_record_id",
            "repository_binding_id",
            "binding_snapshot_json",
            "binding_snapshot_sha256",
            "commit_sha",
            "target_ref",
            "request_hash",
            "approval_id",
            "remote_verified_sha",
            "status",
            "idempotency_key",
            "approved_at",
            "published_at",
            "created_at",
            "updated_at",
        },
        "workflow_jobs": {
            "id",
            "task_id",
            "job_type",
            "resource_type",
            "resource_id",
            "side_effect_class",
            "request_hash",
            "idempotency_key",
            "status",
            "attempt",
            "max_attempts",
            "lease_owner",
            "lease_expires_at",
            "heartbeat_at",
            "next_retry_at",
            "cancel_requested_at",
            "dispatch_lease_owner",
            "dispatch_lease_expires_at",
            "next_enqueue_at",
            "last_enqueued_at",
            "enqueue_attempt",
            "last_enqueue_error_code",
            "payload_json",
            "result_json",
            "error_code",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        },
    }
    expected_constraints = {
        "ck_approval_requests_status",
        "ck_approval_requests_resource_group",
        "ck_approval_requests_request_hash",
        "ck_approval_requests_decision",
        "ck_approval_requests_release_candidate",
        "ck_approval_requests_expiry",
        "ck_approval_requests_decision_before_expiry",
        "ck_approval_requests_consumed",
        "ck_approval_requests_time_order",
        "uq_project_repository_bindings_project",
        "uq_project_repository_bindings_external",
        "ck_project_repository_bindings_provider",
        "ck_project_repository_bindings_status",
        "ck_project_repository_bindings_profile_key",
        "ck_project_repository_bindings_identity",
        "ck_project_repository_bindings_clone_url",
        "ck_project_repository_bindings_config",
        "ck_project_repository_bindings_release_ref_prefix",
        "ck_project_repository_bindings_time_order",
        "uq_release_candidates_task_idempotency",
        "uq_release_candidates_binding_ref",
        "uq_release_candidates_pr_snapshot",
        "ck_release_candidates_status",
        "ck_release_candidates_snapshot",
        "ck_release_candidates_snapshot_hash",
        "ck_release_candidates_commit_sha",
        "ck_release_candidates_remote_sha",
        "ck_release_candidates_request_hash",
        "ck_release_candidates_idempotency_key",
        "ck_release_candidates_target_ref",
        "ck_release_candidates_lifecycle",
        "ck_release_candidates_time_order",
        "uq_workflow_jobs_task_type_idempotency",
        "ck_workflow_jobs_m7_2_handler",
        "ck_workflow_jobs_status",
        "ck_workflow_jobs_request_hash",
        "ck_workflow_jobs_idempotency_key",
        "ck_workflow_jobs_attempts",
        "ck_workflow_jobs_payload_object",
        "ck_workflow_jobs_result_object",
        "ck_workflow_jobs_worker_lease_pair",
        "ck_workflow_jobs_dispatch_lease_pair",
        "ck_workflow_jobs_dispatch_lease_status",
        "ck_workflow_jobs_retry_enqueue",
        "ck_workflow_jobs_enqueue_attempt",
        "ck_workflow_jobs_lifecycle",
        "ck_workflow_jobs_cancel",
        "ck_workflow_jobs_result_semantics",
        "ck_workflow_jobs_time_order",
    }
    expected_index_predicates = {
        "ux_approval_requests_resource_action": (
            "resource_type IS NOT NULL"
        ),
        "ix_approval_requests_resource_status": (
            "resource_type IS NOT NULL"
        ),
        "ix_approval_requests_pending_expiry": (
            "status = 'pending'::text"
        ),
        "ux_release_candidates_task_active": (
            "status = ANY (ARRAY['pending_approval'::text, 'approved'::text])"
        ),
        "ux_workflow_jobs_blocking_resource": (
            "status = ANY (ARRAY['pending'::text, 'claimed'::text"
        ),
        "ix_workflow_jobs_status_lease": (
            "status = ANY (ARRAY['claimed'::text, 'running'::text"
        ),
        "ix_workflow_jobs_due_enqueue": "status = 'pending'::text",
        "ix_workflow_jobs_due_retry": "next_retry_at IS NOT NULL",
    }
    expected_indexes = {
        "ux_project_repository_bindings_owner_name",
        "ix_project_repository_bindings_status_updated",
        "ux_release_candidates_approval",
        "ix_release_candidates_task_status_created",
        "ix_release_candidates_project_created",
        "ix_workflow_jobs_task_created",
        "ix_workflow_jobs_resource_created",
    }
    expected_delete_rules = {
        (
            "project_repository_bindings",
            "project_repository_bindings_project_id_fkey",
        ): "c",
        ("release_candidates", "release_candidates_task_id_fkey"): "c",
        ("release_candidates", "release_candidates_project_id_fkey"): "c",
        (
            "release_candidates",
            "release_candidates_pull_request_record_id_fkey",
        ): "a",
        (
            "release_candidates",
            "release_candidates_repository_binding_id_fkey",
        ): "a",
        (
            "release_candidates",
            "release_candidates_approval_id_fkey",
        ): "a",
        ("workflow_jobs", "workflow_jobs_task_id_fkey"): "c",
    }

    with get_engine().connect() as connection:
        for table_name, expected in expected_columns.items():
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
            if table_name in {
                "project_repository_bindings",
                "release_candidates",
                "workflow_jobs",
            }:
                assert columns == expected
            else:
                assert expected.issubset(columns)

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
    assert expected_indexes.issubset(index_definitions)
    for index_name, predicate in expected_index_predicates.items():
        assert predicate in index_definitions[index_name]
    for identity, delete_rule in expected_delete_rules.items():
        assert delete_rules[identity] == delete_rule


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("provider", None),
        ("repository_owner", 123),
        ("release_ref_prefix", "refs/heads/invalid..candidate"),
    ],
)
def test_m7_release_candidate_snapshot_rejects_null_type_and_ref_violations(
    field_name: str,
    invalid_value: Any,
) -> None:
    """Candidate 安全快照必须是精确八字段、字符串且使用安全 ref。"""

    references = seed_m7_candidate_dependencies()
    snapshot = valid_binding_snapshot()
    snapshot[field_name] = invalid_value

    with Session(get_engine()) as session:
        session.add(
            build_release_candidate(
                references,
                binding_snapshot_json=snapshot,
            )
        )
        with pytest.raises(IntegrityError) as exc_info:
            session.commit()
        assert (
            exc_info.value.orig.diag.constraint_name
            == "ck_release_candidates_snapshot"
        )
        session.rollback()


def test_m7_published_candidate_requires_non_null_matching_remote_sha() -> None:
    """published 不能利用 SQL NULL 绕过远端 commit 精确回读门禁。"""

    references = seed_m7_candidate_dependencies()
    now = utc_now()
    with Session(get_engine()) as session:
        session.add(
            build_release_candidate(
                references,
                status="published",
                approved_at=now,
                published_at=now,
                remote_verified_sha=None,
            )
        )
        with pytest.raises(IntegrityError) as exc_info:
            session.commit()
        assert (
            exc_info.value.orig.diag.constraint_name
            == "ck_release_candidates_lifecycle"
        )
        session.rollback()


def test_m7_valid_candidate_and_workflow_job_use_database_enqueue_time() -> None:
    """合法 Candidate 可落库，WorkflowJob 初始投递时间由 PostgreSQL 生成。"""

    references = seed_m7_candidate_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        candidate = build_release_candidate(references)
        session.add(candidate)
        session.flush()
        job = build_workflow_job(
            references,
            resource_id=candidate.id,
        )
        session.add(job)
        session.flush()
        session.refresh(job)

        assert job.next_enqueue_at is not None
        session.commit()


def test_m7_candidate_prevents_deleting_source_pull_request() -> None:
    """Candidate 存在时 PullRequestRecord 的 NO ACTION 外键必须真实阻断删除。"""

    references = seed_m7_candidate_dependencies()
    with Session(get_engine()) as session:
        session.add(build_release_candidate(references))
        session.commit()

    with Session(get_engine()) as session:
        with pytest.raises(IntegrityError) as exc_info:
            session.execute(
                text(
                    """
                    DELETE FROM pull_request_records
                    WHERE id = :pull_request_record_id
                    """
                ),
                {
                    "pull_request_record_id": references[
                        "pull_request_record_id"
                    ]
                },
            )
            session.commit()
        assert (
            exc_info.value.orig.diag.constraint_name
            == "release_candidates_pull_request_record_id_fkey"
        )
        session.rollback()


def test_m7_ci_deployment_migration_contract() -> None:
    """M7-2D 三表、Approval CHECK、索引和删除规则必须精确落库。"""

    expected_columns = {
        "ci_runs": {
            "task_id",
            "project_id",
            "pull_request_record_id",
            "release_candidate_id",
            "provider",
            "repository_external_id",
            "external_run_id",
            "external_job_id",
            "workflow_id",
            "workflow_revision",
            "source_ref",
            "commit_sha",
            "status",
            "idempotency_key",
            "last_event_action",
            "last_event_status",
            "last_delivery_id",
            "provider_head_sha",
            "provider_updated_at",
            "artifact_manifest_id",
            "image_index_digest",
            "platform_manifest_digest",
            "started_at",
            "finished_at",
            "id",
            "created_at",
            "updated_at",
        },
        "deployments": {
            "task_id",
            "project_id",
            "environment_id",
            "remote_target_id",
            "ci_run_id",
            "release_plan_artifact_id",
            "commit_sha",
            "image_ref",
            "image_digest",
            "platform_manifest_digest",
            "release_version",
            "request_hash",
            "approval_id",
            "remote_operation_id",
            "status",
            "health_summary_json",
            "failure_code",
            "failure_summary",
            "requested_by_actor",
            "approved_by_actor",
            "dispatched_by_agent_run_id",
            "idempotency_key",
            "started_at",
            "finished_at",
            "rollback_candidate_id",
            "rollback_request_artifact_id",
            "id",
            "created_at",
            "updated_at",
        },
        "service_instances": {
            "deployment_id",
            "environment_id",
            "remote_target_id",
            "service_name",
            "compose_project",
            "runtime_type",
            "runtime_ref",
            "image_digest",
            "status",
            "health_url",
            "health_result_json",
            "last_health_check_at",
            "last_error_code",
            "id",
            "created_at",
            "updated_at",
        },
    }
    expected_constraints = {
        "ck_approval_requests_deployment",
        "ck_approval_requests_m7_resource_action_group",
        "ck_ci_runs_provider",
        "ck_ci_runs_status",
        "ck_ci_runs_repository_identity",
        "ck_ci_runs_external_identity",
        "ck_ci_runs_workflow_identity",
        "ck_ci_runs_workflow_revision",
        "ck_ci_runs_source_ref",
        "ck_ci_runs_commit_sha",
        "ck_ci_runs_provider_head_sha",
        "ck_ci_runs_digests",
        "ck_ci_runs_idempotency_key",
        "ck_ci_runs_provider_event_group",
        "ck_ci_runs_lifecycle",
        "ck_ci_runs_time_order",
        "uq_ci_runs_release_candidate",
        "uq_ci_runs_task_idempotency",
        "ck_deployments_status",
        "ck_deployments_commit_sha",
        "ck_deployments_image_ref",
        "ck_deployments_digests",
        "ck_deployments_release_version",
        "ck_deployments_request_hash",
        "ck_deployments_idempotency_key",
        "ck_deployments_health_summary_object",
        "ck_deployments_health_summary_safe",
        "ck_deployments_failure_evidence",
        "ck_deployments_approval_lifecycle",
        "ck_deployments_operation_lifecycle",
        "ck_deployments_health_lifecycle",
        "ck_deployments_rollback",
        "ck_deployments_actor_fields",
        "ck_deployments_time_order",
        "uq_deployments_task_idempotency",
        "uq_deployments_environment_release_version",
        "ck_service_instances_runtime_type",
        "ck_service_instances_status",
        "ck_service_instances_slugs",
        "ck_service_instances_runtime_ref",
        "ck_service_instances_image_digest",
        "ck_service_instances_health_url",
        "ck_service_instances_health_result_object",
        "ck_service_instances_health_result_safe",
        "ck_service_instances_health_lifecycle",
        "ck_service_instances_error_code",
        "ck_service_instances_time_order",
        "uq_service_instances_deployment_service",
    }
    expected_indexes = {
        "ux_ci_runs_provider_repository_run",
        "ix_ci_runs_task_created",
        "ix_ci_runs_project_created",
        "ux_deployments_approval",
        "ux_deployments_remote_target_operation",
        "ix_deployments_task_created",
        "ix_deployments_project_created",
        "ix_deployments_environment_created",
        "ix_service_instances_environment_status_created",
        "ix_service_instances_remote_target_status_created",
    }
    expected_delete_rules = {
        ("ci_runs", "ci_runs_task_id_fkey"): "c",
        ("ci_runs", "ci_runs_project_id_fkey"): "c",
        ("ci_runs", "ci_runs_pull_request_record_id_fkey"): "a",
        ("ci_runs", "ci_runs_release_candidate_id_fkey"): "a",
        ("ci_runs", "ci_runs_artifact_manifest_id_fkey"): "a",
        ("deployments", "deployments_task_id_fkey"): "c",
        ("deployments", "deployments_project_id_fkey"): "c",
        ("deployments", "deployments_environment_id_fkey"): "a",
        ("deployments", "deployments_remote_target_id_fkey"): "a",
        ("deployments", "deployments_ci_run_id_fkey"): "a",
        (
            "deployments",
            "deployments_release_plan_artifact_id_fkey",
        ): "a",
        ("deployments", "deployments_approval_id_fkey"): "a",
        (
            "deployments",
            "deployments_dispatched_by_agent_run_id_fkey",
        ): "n",
        (
            "deployments",
            "deployments_rollback_candidate_id_fkey",
        ): "a",
        (
            "deployments",
            "deployments_rollback_request_artifact_id_fkey",
        ): "a",
        (
            "service_instances",
            "service_instances_deployment_id_fkey",
        ): "c",
        (
            "service_instances",
            "service_instances_environment_id_fkey",
        ): "a",
        (
            "service_instances",
            "service_instances_remote_target_id_fkey",
        ): "a",
    }
    expected_nullable = {
        "ci_runs": {
            "external_run_id",
            "external_job_id",
            "last_event_action",
            "last_event_status",
            "last_delivery_id",
            "provider_head_sha",
            "provider_updated_at",
            "artifact_manifest_id",
            "image_index_digest",
            "platform_manifest_digest",
            "started_at",
            "finished_at",
        },
        "deployments": {
            "approval_id",
            "remote_operation_id",
            "health_summary_json",
            "failure_code",
            "failure_summary",
            "approved_by_actor",
            "dispatched_by_agent_run_id",
            "started_at",
            "finished_at",
            "rollback_candidate_id",
            "rollback_request_artifact_id",
        },
        "service_instances": {
            "runtime_ref",
            "health_url",
            "health_result_json",
            "last_health_check_at",
            "last_error_code",
        },
    }
    expected_types = {
        "uuid": {
            ("ci_runs", column)
            for column in {
                "task_id",
                "project_id",
                "pull_request_record_id",
                "release_candidate_id",
                "artifact_manifest_id",
                "id",
            }
        }
        | {
            ("deployments", column)
            for column in {
                "task_id",
                "project_id",
                "environment_id",
                "remote_target_id",
                "ci_run_id",
                "release_plan_artifact_id",
                "approval_id",
                "dispatched_by_agent_run_id",
                "rollback_candidate_id",
                "rollback_request_artifact_id",
                "id",
            }
        }
        | {
            ("service_instances", column)
            for column in {
                "deployment_id",
                "environment_id",
                "remote_target_id",
                "id",
            }
        },
        "text": {
            ("ci_runs", column)
            for column in {
                "provider",
                "repository_external_id",
                "external_run_id",
                "external_job_id",
                "workflow_id",
                "workflow_revision",
                "source_ref",
                "commit_sha",
                "status",
                "idempotency_key",
                "last_event_action",
                "last_event_status",
                "last_delivery_id",
                "provider_head_sha",
                "image_index_digest",
                "platform_manifest_digest",
            }
        }
        | {
            ("deployments", column)
            for column in {
                "commit_sha",
                "image_ref",
                "image_digest",
                "platform_manifest_digest",
                "release_version",
                "request_hash",
                "remote_operation_id",
                "status",
                "failure_code",
                "failure_summary",
                "requested_by_actor",
                "approved_by_actor",
                "idempotency_key",
            }
        }
        | {
            ("service_instances", column)
            for column in {
                "service_name",
                "compose_project",
                "runtime_type",
                "runtime_ref",
                "image_digest",
                "status",
                "health_url",
                "last_error_code",
            }
        },
        "timestamp with time zone": {
            ("ci_runs", column)
            for column in {
                "provider_updated_at",
                "started_at",
                "finished_at",
                "created_at",
                "updated_at",
            }
        }
        | {
            ("deployments", column)
            for column in {
                "started_at",
                "finished_at",
                "created_at",
                "updated_at",
            }
        }
        | {
            ("service_instances", column)
            for column in {
                "last_health_check_at",
                "created_at",
                "updated_at",
            }
        },
        "jsonb": {
            ("deployments", "health_summary_json"),
            ("service_instances", "health_result_json"),
        },
    }
    expected_server_defaults = {
        ("ci_runs", "provider"): "'gitea'::text",
        ("ci_runs", "status"): "'triggered'::text",
        ("ci_runs", "created_at"): "now()",
        ("ci_runs", "updated_at"): "now()",
        ("deployments", "status"): "'planned'::text",
        ("deployments", "created_at"): "now()",
        ("deployments", "updated_at"): "now()",
        ("service_instances", "runtime_type"): "'docker_compose'::text",
        ("service_instances", "status"): "'starting'::text",
        ("service_instances", "created_at"): "now()",
        ("service_instances", "updated_at"): "now()",
    }
    expected_index_contracts = {
        "ux_ci_runs_provider_repository_run": (
            True,
            "(external_run_id IS NOT NULL)",
            "(provider, repository_external_id, external_run_id)",
        ),
        "ix_ci_runs_task_created": (
            False,
            None,
            "(task_id, created_at DESC, id DESC)",
        ),
        "ix_ci_runs_project_created": (
            False,
            None,
            "(project_id, created_at DESC, id DESC)",
        ),
        "ux_deployments_approval": (
            True,
            "(approval_id IS NOT NULL)",
            "(approval_id)",
        ),
        "ux_deployments_remote_target_operation": (
            True,
            "(remote_operation_id IS NOT NULL)",
            "(remote_target_id, remote_operation_id)",
        ),
        "ix_deployments_task_created": (
            False,
            None,
            "(task_id, created_at DESC, id DESC)",
        ),
        "ix_deployments_project_created": (
            False,
            None,
            "(project_id, created_at DESC, id DESC)",
        ),
        "ix_deployments_environment_created": (
            False,
            None,
            "(environment_id, created_at DESC, id DESC)",
        ),
        "ix_service_instances_environment_status_created": (
            False,
            None,
            "(environment_id, status, created_at DESC, id DESC)",
        ),
        "ix_service_instances_remote_target_status_created": (
            False,
            None,
            "(remote_target_id, status, created_at DESC, id DESC)",
        ),
    }

    with get_engine().connect() as connection:
        column_metadata = {}
        for table_name, expected in expected_columns.items():
            rows = list(
                connection.execute(
                    text(
                        """
                        SELECT
                            column_name,
                            data_type,
                            is_nullable,
                            column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            )
            columns = {
                row.column_name
                for row in rows
            }
            column_metadata.update(
                {
                    (table_name, row.column_name): row
                    for row in rows
                }
            )
            assert columns == expected

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
        index_contracts = {
            row.index_name: row
            for row in connection.execute(
                text(
                    """
                    SELECT
                        index_relation.relname AS index_name,
                        index_record.indisunique,
                        pg_get_expr(
                            index_record.indpred,
                            index_record.indrelid
                        ) AS predicate,
                        pg_get_indexdef(index_record.indexrelid)
                            AS index_definition
                    FROM pg_index AS index_record
                    JOIN pg_class AS index_relation
                      ON index_relation.oid = index_record.indexrelid
                    JOIN pg_class AS table_relation
                      ON table_relation.oid = index_record.indrelid
                    WHERE table_relation.relnamespace
                      = 'public'::regnamespace
                      AND table_relation.relname IN (
                        'ci_runs',
                        'deployments',
                        'service_instances'
                      )
                    """
                )
            )
        }
        indexes = set(index_contracts)
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
                      AND constraint_record.connamespace
                        = 'public'::regnamespace
                    """
                )
            )
        }

    for table_name, columns in expected_columns.items():
        nullable = {
            column_name
            for column_name in columns
            if column_metadata[(table_name, column_name)].is_nullable
            == "YES"
        }
        assert nullable == expected_nullable[table_name]

    expected_type_by_column = {
        identity: data_type
        for data_type, identities in expected_types.items()
        for identity in identities
    }
    assert set(expected_type_by_column) == {
        (table_name, column_name)
        for table_name, columns in expected_columns.items()
        for column_name in columns
    }
    for identity, expected_type in expected_type_by_column.items():
        assert column_metadata[identity].data_type == expected_type

    for identity, row in column_metadata.items():
        assert row.column_default == expected_server_defaults.get(identity)

    assert expected_constraints.issubset(constraints)
    assert expected_indexes.issubset(indexes)
    for index_name, expected in expected_index_contracts.items():
        unique, predicate, definition_fragment = expected
        row = index_contracts[index_name]
        assert row.indisunique is unique
        assert row.predicate == predicate
        assert definition_fragment in row.index_definition
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
