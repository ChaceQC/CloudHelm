"""M7-2D 三值逻辑、脱敏和严格生命周期回归测试。"""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.approval import ApprovalRequest

from m7_ci_deployment_fixture import (
    IMAGE_DIGEST,
    build_ci_run,
    build_deployment,
    build_healthy_deployment,
    build_passed_ci_run,
    build_service_instance,
    seed_m7_ci_deployment_dependencies,
)


def _assert_constraint(
    session: Session,
    value: Any,
    constraint_name: str,
) -> None:
    """提交非法 ORM 记录并断言 PostgreSQL 精确约束名。"""

    session.add(value)
    with pytest.raises(IntegrityError) as exc_info:
        session.commit()
    assert exc_info.value.orig.diag.constraint_name == constraint_name
    session.rollback()


def _assert_sql_constraint(
    session: Session,
    statement: str,
    parameters: dict[str, Any],
    constraint_name: str,
) -> None:
    """执行原始 SQL 并断言数据库门禁，覆盖 JSON literal null。"""

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(text(statement), parameters)
        session.commit()
    assert exc_info.value.orig.diag.constraint_name == constraint_name
    session.rollback()


@pytest.mark.parametrize("status", ["running", "passed"])
def test_ci_run_requires_external_run_identity_after_trigger(
    status: str,
) -> None:
    """running/passed 不得保留 provider run identity 空窗。"""

    references = seed_m7_ci_deployment_dependencies()
    overrides: dict[str, Any] = {
        "status": status,
        "started_at": references.now,
    }
    if status == "passed":
        overrides.update(
            {
                "finished_at": references.now + timedelta(seconds=1),
                "provider_head_sha": "1" * 40,
                "artifact_manifest_id": references.ci_manifest_artifact_id,
                "image_index_digest": IMAGE_DIGEST,
                "platform_manifest_digest": "sha256:" + ("b" * 64),
            }
        )
    with Session(get_engine()) as session:
        _assert_constraint(
            session,
            build_ci_run(references, **overrides),
            "ck_ci_runs_lifecycle",
        )


def test_ci_run_rejects_timestamped_half_provider_event_group() -> None:
    """timestamp 非空时仍必须显式提供三个 provider event identity 字段。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine()) as session:
        _assert_constraint(
            session,
            build_ci_run(
                references,
                last_event_action="completed",
                provider_updated_at=references.now,
            ),
            "ck_ci_runs_provider_event_group",
        )


def test_failed_deployment_requires_non_null_failure_code() -> None:
    """SQL 三值逻辑不能让 failed + NULL failure_code 通过。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        _assert_constraint(
            session,
            build_deployment(
                references,
                ci_run_id=ci_run.id,
                status="failed",
                finished_at=references.now,
                failure_code=None,
            ),
            "ck_deployments_failure_evidence",
        )


@pytest.mark.parametrize(
    "image_ref",
    [
        f"user@registry.example.test/sample@{IMAGE_DIGEST}",
        f"https://registry.example.test/sample@{IMAGE_DIGEST}",
    ],
)
def test_deployment_rejects_userinfo_or_scheme_image_ref(
    image_ref: str,
) -> None:
    """OCI image ref 只能具有一个 digest 分隔符，不能伪装 URL。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        _assert_constraint(
            session,
            build_deployment(
                references,
                ci_run_id=ci_run.id,
                image_ref=image_ref,
            ),
            "ck_deployments_image_ref",
        )


@pytest.mark.parametrize(
    "health_summary",
    [
        {"token": "example-sensitive-value"},
        {"raw_logs": "example raw output"},
        {"status": {"nested": "object"}},
        {"Bad-Key": "invalid"},
        {"summary": "x" * 513},
    ],
)
def test_deployment_rejects_unsafe_health_summary(
    health_summary: dict[str, Any],
) -> None:
    """健康摘要拒绝敏感键、嵌套值、非法 key 和超长文本。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        _assert_constraint(
            session,
            build_deployment(
                references,
                ci_run_id=ci_run.id,
                health_summary_json=health_summary,
            ),
            "ck_deployments_health_summary_safe",
        )


def test_health_json_literal_null_is_not_an_object() -> None:
    """SQL NULL 可空，但 JSONB literal null 必须命中 object CHECK。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        deployment = build_deployment(
            references,
            ci_run_id=ci_run.id,
        )
        session.add(deployment)
        session.commit()
        _assert_sql_constraint(
            session,
            """
            UPDATE deployments
            SET health_summary_json = 'null'::jsonb
            WHERE id = :deployment_id
            """,
            {"deployment_id": deployment.id},
            "ck_deployments_health_summary_object",
        )

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        deployment = build_healthy_deployment(
            references,
            ci_run_id=ci_run.id,
        )
        session.add(deployment)
        session.flush()
        instance = build_service_instance(
            references,
            deployment_id=deployment.id,
        )
        session.add(instance)
        session.commit()
        _assert_sql_constraint(
            session,
            """
            UPDATE service_instances
            SET health_result_json = 'null'::jsonb,
                last_health_check_at = created_at
            WHERE id = :instance_id
            """,
            {"instance_id": instance.id},
            "ck_service_instances_health_result_object",
        )


def test_service_instance_rejects_userinfo_and_raw_health_output() -> None:
    """健康 URL 不接受 userinfo，结果对象不接受原始日志字段。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        deployment = build_healthy_deployment(
            references,
            ci_run_id=ci_run.id,
        )
        session.add(deployment)
        session.flush()
        _assert_constraint(
            session,
            build_service_instance(
                references,
                deployment_id=deployment.id,
                health_url=(
                    "https://user:password@staging.example.test/health"
                ),
            ),
            "ck_service_instances_health_url",
        )

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        deployment = build_healthy_deployment(
            references,
            ci_run_id=ci_run.id,
        )
        session.add(deployment)
        session.flush()
        _assert_constraint(
            session,
            build_service_instance(
                references,
                deployment_id=deployment.id,
                health_result_json={"stderr": "example raw output"},
                last_health_check_at=references.now,
            ),
            "ck_service_instances_health_result_safe",
        )


@pytest.mark.parametrize(
    ("overrides", "constraint_name"),
    [
        (
            {
                "approval_id": None,
                "approved_by_actor": None,
            },
            "ck_deployments_approval_lifecycle",
        ),
        (
            {
                "remote_operation_id": None,
                "started_at": None,
            },
            "ck_deployments_operation_lifecycle",
        ),
        (
            {
                "health_summary_json": None,
            },
            "ck_deployments_health_lifecycle",
        ),
    ],
)
def test_rollback_requested_requires_complete_execution_evidence(
    overrides: dict[str, Any],
    constraint_name: str,
) -> None:
    """rollback 请求必须保留审批、operation、时间与健康证据。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        values: dict[str, Any] = {
            "ci_run_id": ci_run.id,
            "status": "rollback_requested",
            "approval_id": references.deployment_approval_id,
            "approved_by_actor": "reviewer",
            "remote_operation_id": "operation-rollback",
            "started_at": references.now,
            "finished_at": references.now + timedelta(seconds=1),
            "health_summary_json": {"status": "unhealthy"},
            "rollback_candidate_id": references.historical_deployment_id,
            "rollback_request_artifact_id": (
                references.rollback_request_artifact_id
            ),
        }
        values.update(overrides)
        _assert_constraint(
            session,
            build_deployment(references, **values),
            constraint_name,
        )


def test_rollback_requested_rejects_self_reference() -> None:
    """rollback candidate 不能引用当前 Deployment 自身。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        _assert_constraint(
            session,
            build_deployment(
                references,
                ci_run_id=ci_run.id,
                status="rollback_requested",
                approval_id=references.deployment_approval_id,
                approved_by_actor="reviewer",
                remote_operation_id="operation-rollback-self",
                started_at=references.now,
                finished_at=references.now + timedelta(seconds=1),
                health_summary_json={"status": "unhealthy"},
                rollback_candidate_id=references.deployment_id,
                rollback_request_artifact_id=(
                    references.rollback_request_artifact_id
                ),
            ),
            "ck_deployments_rollback",
        )


def test_resource_approval_action_cannot_omit_resource_identity() -> None:
    """历史 release action 也不能借 SQL NULL 绕过资源组合门禁。"""

    references = seed_m7_ci_deployment_dependencies()
    invalid = ApprovalRequest(
        task_id=references.task_id,
        action="approve_release_candidate",
        risk_level="L2",
        reason="缺少资源 identity。",
        status="pending",
        requested_by_agent_run_id=references.requester_agent_run_id,
        created_at=references.now,
    )
    with Session(get_engine()) as session:
        _assert_constraint(
            session,
            invalid,
            "ck_approval_requests_m7_resource_action_group",
        )
