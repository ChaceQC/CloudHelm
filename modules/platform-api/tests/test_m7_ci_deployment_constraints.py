"""M7-2D CI、部署与服务实例数据库约束测试。"""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.approval import ApprovalRequest

from m7_ci_deployment_fixture import (
    IMAGE_DIGEST,
    PLATFORM_DIGEST,
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
    """提交单条非法记录并断言 PostgreSQL 精确约束名。"""

    session.add(value)
    with pytest.raises(IntegrityError) as exc_info:
        session.commit()
    assert exc_info.value.orig.diag.constraint_name == constraint_name
    session.rollback()


@pytest.mark.parametrize(
    ("status", "overrides"),
    [
        ("triggered", {}),
        (
            "running",
            {
                "external_run_id": "run-running",
                "started_at": "now",
            },
        ),
        (
            "passed",
            {
                "external_run_id": "run-passed",
                "started_at": "now",
                "finished_at": "later",
                "provider_head_sha": "commit",
                "artifact_manifest_id": "manifest",
                "image_index_digest": IMAGE_DIGEST,
                "platform_manifest_digest": PLATFORM_DIGEST,
            },
        ),
        ("failed", {"finished_at": "later"}),
        ("cancelled", {"finished_at": "later"}),
    ],
)
def test_ci_run_accepts_each_frozen_status(
    status: str,
    overrides: dict[str, Any],
) -> None:
    """CIRun 五个冻结状态均具有至少一种合法持久化形态。"""

    references = seed_m7_ci_deployment_dependencies()
    values = dict(overrides)
    values["status"] = status
    for key, marker in list(values.items()):
        if marker == "now":
            values[key] = references.now
        elif marker == "later":
            values[key] = references.now + timedelta(seconds=1)
        elif marker == "commit":
            values[key] = "1" * 40
        elif marker == "manifest":
            values[key] = references.ci_manifest_artifact_id

    with Session(get_engine()) as session:
        session.add(build_ci_run(references, **values))
        session.commit()


@pytest.mark.parametrize(
    ("status", "overrides"),
    [
        ("planned", {}),
        (
            "pending_approval",
            {"approval_id": "approval"},
        ),
        (
            "queued",
            {
                "approval_id": "approval",
                "approved_by_actor": "reviewer",
            },
        ),
        (
            "deploying",
            {
                "approval_id": "approval",
                "approved_by_actor": "reviewer",
                "remote_operation_id": "op-deploying",
                "started_at": "now",
            },
        ),
        (
            "verifying",
            {
                "approval_id": "approval",
                "approved_by_actor": "reviewer",
                "remote_operation_id": "op-verifying",
                "started_at": "now",
            },
        ),
        (
            "healthy",
            {
                "approval_id": "approval",
                "approved_by_actor": "reviewer",
                "remote_operation_id": "op-healthy",
                "started_at": "now",
                "finished_at": "later",
                "health_summary_json": {"status": "ok"},
            },
        ),
        (
            "unhealthy",
            {
                "approval_id": "approval",
                "approved_by_actor": "reviewer",
                "remote_operation_id": "op-unhealthy",
                "started_at": "now",
                "finished_at": "later",
                "health_summary_json": {"status": "unhealthy"},
            },
        ),
        (
            "failed",
            {
                "finished_at": "later",
                "failure_code": "deployment_failed",
                "failure_summary": "脱敏失败摘要",
            },
        ),
        (
            "cancelled",
            {"finished_at": "later"},
        ),
    ],
)
def test_deployment_accepts_non_rollback_statuses(
    status: str,
    overrides: dict[str, Any],
) -> None:
    """除 rollback_requested 外的冻结状态均可合法落库。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        values = dict(overrides)
        values["status"] = status
        for key, marker in list(values.items()):
            if marker == "approval":
                values[key] = references.deployment_approval_id
            elif marker == "now":
                values[key] = references.now
            elif marker == "later":
                values[key] = references.now + timedelta(seconds=1)
        session.add(
            build_deployment(
                references,
                ci_run_id=ci_run.id,
                **values,
            )
        )
        session.commit()


def test_deployment_accepts_rollback_requested_with_historical_candidate() -> None:
    """rollback_requested 必须引用另一条历史 Deployment 与 request Artifact。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        historical = build_healthy_deployment(
            references,
            ci_run_id=ci_run.id,
            id=references.historical_deployment_id,
            approval_id=references.historical_deployment_approval_id,
            remote_operation_id="operation-historical-healthy",
            release_version="0.5.9",
            idempotency_key=f"deployment:{uuid4()}",
        )
        session.add(historical)
        session.flush()
        rollback = build_deployment(
            references,
            ci_run_id=ci_run.id,
            release_version="0.6.0-rollback-request",
            approval_id=references.deployment_approval_id,
            approved_by_actor="reviewer",
            remote_operation_id="operation-rollback-request",
            status="rollback_requested",
            health_summary_json={"status": "unhealthy"},
            started_at=references.now,
            finished_at=references.now + timedelta(seconds=1),
            rollback_candidate_id=historical.id,
            rollback_request_artifact_id=(
                references.rollback_request_artifact_id
            ),
        )
        session.add(rollback)
        session.commit()


@pytest.mark.parametrize(
    ("status", "overrides"),
    [
        ("starting", {}),
        ("running", {}),
        (
            "healthy",
            {
                "health_result_json": {"status": "ok"},
                "last_health_check_at": "now",
            },
        ),
        (
            "unhealthy",
            {
                "health_result_json": {"status": "failed"},
                "last_health_check_at": "now",
            },
        ),
        ("stopped", {}),
        ("failed", {"last_error_code": "container_failed"}),
    ],
)
def test_service_instance_accepts_each_frozen_status(
    status: str,
    overrides: dict[str, Any],
) -> None:
    """ServiceInstance 六个冻结状态均具有合法形态。"""

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
        values = dict(overrides)
        values["status"] = status
        if values.get("last_health_check_at") == "now":
            values["last_health_check_at"] = references.now
        session.add(
            build_service_instance(
                references,
                deployment_id=deployment.id,
                **values,
            )
        )
        session.commit()


def test_ci_run_rejects_unsafe_ref_and_incomplete_passed_evidence() -> None:
    """CIRun ref 与 passed 证据分别命中精确 CHECK。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine()) as session:
        _assert_constraint(
            session,
            build_ci_run(references, source_ref="refs/heads/bad..ref"),
            "ck_ci_runs_source_ref",
        )
        _assert_constraint(
            session,
            build_ci_run(
                references,
                id=uuid4(),
                status="passed",
                started_at=references.now,
                finished_at=references.now,
            ),
            "ck_ci_runs_lifecycle",
        )


def test_ci_run_rejects_partial_provider_event_group() -> None:
    """provider 幂等线索不能只写 action 而缺其余比较字段。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine()) as session:
        _assert_constraint(
            session,
            build_ci_run(
                references,
                last_event_action="completed",
            ),
            "ck_ci_runs_provider_event_group",
        )


def test_deployment_rejects_mutable_image_and_missing_approval() -> None:
    """Deployment 固定 digest 与 pending Approval 都由数据库门禁。"""

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
                image_ref="registry.example.test/sample:latest",
            ),
            "ck_deployments_image_ref",
        )

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
                status="pending_approval",
            ),
            "ck_deployments_approval_lifecycle",
        )


def test_deployment_and_service_reject_non_object_health_evidence() -> None:
    """健康摘要必须是 JSON object，不能用 array 冒充。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = build_passed_ci_run(references)
        session.add(ci_run)
        session.flush()
        deployment = build_deployment(
            references,
            ci_run_id=ci_run.id,
            approval_id=references.deployment_approval_id,
            approved_by_actor="reviewer",
            remote_operation_id="op-health",
            status="healthy",
            started_at=references.now,
            finished_at=references.now,
            health_summary_json=[],
        )
        _assert_constraint(
            session,
            deployment,
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
            status="healthy",
            health_result_json=[],
            last_health_check_at=references.now,
        )
        _assert_constraint(
            session,
            instance,
            "ck_service_instances_health_result_object",
        )


def test_service_instance_rejects_unknown_runtime_and_missing_health() -> None:
    """M7 runtime 固定且 healthy 必须有结构化证据。"""

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
                runtime_type="kubernetes",
            ),
            "ck_service_instances_runtime_type",
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
                status="healthy",
            ),
            "ck_service_instances_health_lifecycle",
        )


def test_deployment_approval_requires_l3_agent_requester() -> None:
    """deployment resource 不能使用 L2 或缺少 AgentRun 发起者。"""

    references = seed_m7_ci_deployment_dependencies()
    invalid = ApprovalRequest(
        task_id=references.task_id,
        action="approve_deployment",
        risk_level="L2",
        reason="非法风险等级。",
        resource_type="deployment",
        resource_id=uuid4(),
        request_hash="sha256:" + ("f" * 64),
        status="pending",
        requested_by_agent_run_id=references.requester_agent_run_id,
        expires_at=references.now + timedelta(minutes=30),
        created_at=references.now,
    )
    with Session(get_engine()) as session:
        _assert_constraint(
            session,
            invalid,
            "ck_approval_requests_deployment",
        )
        _assert_constraint(
            session,
            ApprovalRequest(
                task_id=references.task_id,
                action="approve_deployment",
                risk_level="L3",
                reason="缺少 AgentRun 发起者。",
                resource_type="deployment",
                resource_id=uuid4(),
                request_hash="sha256:" + ("e" * 64),
                status="pending",
                requested_by_agent_run_id=None,
                expires_at=references.now + timedelta(minutes=30),
                created_at=references.now,
            ),
            "ck_approval_requests_deployment",
        )
