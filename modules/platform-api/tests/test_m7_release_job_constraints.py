"""M7-2A 数据约束、唯一性、外键行为和数据库默认值回归。"""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import null, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)

from m7_release_job_fixture import (
    build_release_candidate,
    build_release_candidate_approval,
    build_workflow_job,
    seed_m7_candidate_dependencies,
    valid_binding_snapshot,
)


@pytest.fixture()
def m7_references() -> dict[str, Any]:
    """为当前用例准备父记录；autouse 清库后必须逐测试重新创建。"""

    return seed_m7_candidate_dependencies(pull_request_count=3)


def _constraint_name(error: IntegrityError) -> str | None:
    """提取 PostgreSQL 返回的真实约束名，避免负测命中错误门禁。"""

    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


def _assert_constraint_violation(
    session: Session,
    instance: Any,
    expected: str | set[str],
) -> None:
    """断言一次写入被指定数据库约束拒绝，并清理失败事务。"""

    session.add(instance)
    with pytest.raises(IntegrityError) as exc_info:
        session.flush()
    actual = _constraint_name(exc_info.value)
    allowed = {expected} if isinstance(expected, str) else expected
    assert actual in allowed, f"expected={sorted(allowed)}, actual={actual}"
    session.rollback()


def _seed_project() -> UUID:
    """创建一条轻量 Project，供 Binding 约束用例独占使用。"""

    suffix = uuid4().hex
    with Session(get_engine(), expire_on_commit=False) as session:
        project = Project(
            name=f"M7 Binding {suffix}",
            repo_url=f"local://m7-binding/{suffix}",
            default_branch="main",
            provider="local",
        )
        session.add(project)
        session.commit()
        return project.id


def _build_binding(
    project_id: UUID,
    *,
    suffix: str | None = None,
    **overrides: Any,
) -> ProjectRepositoryBinding:
    """构造默认合法且 identity 唯一的 RepositoryBinding。"""

    identity = suffix or uuid4().hex[:12]
    values: dict[str, Any] = {
        "project_id": project_id,
        "provider": "gitea",
        "profile_key": f"profile-{identity}",
        "repository_external_id": f"repo-{identity}",
        "repository_owner": f"owner-{identity}",
        "repository_name": f"service-{identity}",
        "clone_url": (
            f"https://gitea.example.test/owner-{identity}/"
            f"service-{identity}.git"
        ),
        "default_branch": "main",
        "credential_ref": f"credential:m7:{identity}",
        "workflow_id": ".gitea/workflows/cloudhelm-release.yml",
        "release_ref_prefix": "refs/heads/cloudhelm/release-candidates",
        "status": "active",
    }
    values.update(overrides)
    return ProjectRepositoryBinding(**values)


@pytest.mark.parametrize(
    "case_name",
    [
        "invalid_status",
        "partial_resource_group",
        "invalid_request_hash",
        "pending_has_decision",
        "release_candidate_wrong_risk",
        "expiry_not_after_create",
        "decision_not_before_expiry",
        "consumed_at_expiry",
        "decision_before_create",
    ],
)
def test_m7_approval_check_constraints_reject_invalid_rows(
    m7_references: dict[str, Any],
    case_name: str,
) -> None:
    """Approval 的每类新增 CHECK 必须由真实 PostgreSQL 写入负测覆盖。"""

    now = utc_now()
    approval = build_release_candidate_approval(
        task_id=m7_references["task_id"],
        requested_by_agent_run_id=m7_references["creator_agent_run_id"],
        candidate_id=uuid4(),
        request_hash="sha256:" + ("e" * 64),
        now=now,
    )
    expected: str | set[str]
    if case_name == "invalid_status":
        approval.status = "waiting"
        expected = {
            "ck_approval_requests_status",
            "ck_approval_requests_decision",
        }
    elif case_name == "partial_resource_group":
        approval.resource_id = None
        expected = "ck_approval_requests_resource_group"
    elif case_name == "invalid_request_hash":
        approval.request_hash = "sha256:ABC"
        expected = "ck_approval_requests_request_hash"
    elif case_name == "pending_has_decision":
        approval.decided_by = "reviewer"
        approval.decided_at = now
        expected = "ck_approval_requests_decision"
    elif case_name == "release_candidate_wrong_risk":
        approval.risk_level = "L3"
        expected = "ck_approval_requests_release_candidate"
    elif case_name == "expiry_not_after_create":
        approval.expires_at = now
        expected = "ck_approval_requests_expiry"
    elif case_name == "decision_not_before_expiry":
        approval.status = "approved"
        approval.decided_by = "reviewer"
        approval.decided_at = approval.expires_at
        expected = "ck_approval_requests_decision_before_expiry"
    elif case_name == "consumed_at_expiry":
        approval.status = "approved"
        approval.decided_by = "reviewer"
        approval.decided_at = now + timedelta(minutes=1)
        approval.consumed_at = approval.expires_at
        expected = "ck_approval_requests_consumed"
    else:
        approval.resource_type = None
        approval.resource_id = None
        approval.request_hash = None
        approval.expires_at = None
        approval.action = "approve_design"
        approval.risk_level = "L1"
        approval.status = "approved"
        approval.decided_by = "reviewer"
        approval.decided_at = now - timedelta(seconds=1)
        expected = "ck_approval_requests_time_order"

    with Session(get_engine()) as session:
        _assert_constraint_violation(session, approval, expected)


def test_m7_approval_resource_action_is_unique(
    m7_references: dict[str, Any],
) -> None:
    """同一资源和 action 的第二条 Approval 必须命中部分唯一索引。"""

    resource_id = uuid4()
    first = build_release_candidate_approval(
        task_id=m7_references["task_id"],
        requested_by_agent_run_id=m7_references["creator_agent_run_id"],
        candidate_id=resource_id,
        request_hash="sha256:" + ("f" * 64),
    )
    second = build_release_candidate_approval(
        task_id=m7_references["task_id"],
        requested_by_agent_run_id=m7_references["creator_agent_run_id"],
        candidate_id=resource_id,
        request_hash="sha256:" + ("0" * 64),
    )
    with Session(get_engine()) as session:
        session.add(first)
        session.flush()
        _assert_constraint_violation(
            session,
            second,
            "ux_approval_requests_resource_action",
        )


def test_m7_cancelled_resource_approval_has_complete_decision_audit(
    m7_references: dict[str, Any],
) -> None:
    """新增 cancelled 状态必须只在完整决定字段存在时允许落库。"""

    now = utc_now()
    approval = build_release_candidate_approval(
        task_id=m7_references["task_id"],
        requested_by_agent_run_id=m7_references["creator_agent_run_id"],
        candidate_id=uuid4(),
        request_hash="sha256:" + ("1" * 64),
        now=now,
        status="cancelled",
        decided_by="system:test",
        decided_at=now,
    )
    with Session(get_engine()) as session:
        session.add(approval)
        session.flush()
        session.rollback()


@pytest.mark.parametrize(
    ("overrides", "expected_constraint"),
    [
        ({"provider": "github"}, "ck_project_repository_bindings_provider"),
        ({"status": "pending"}, "ck_project_repository_bindings_status"),
        ({"profile_key": ".hidden"}, "ck_project_repository_bindings_profile_key"),
        ({"repository_owner": " "}, "ck_project_repository_bindings_identity"),
        ({"clone_url": "http://gitea.example.test/repo.git"}, "ck_project_repository_bindings_clone_url"),
        ({"default_branch": " "}, "ck_project_repository_bindings_config"),
        ({"release_ref_prefix": "refs/heads/.hidden"}, "ck_project_repository_bindings_release_ref_prefix"),
        ({"release_ref_prefix": "refs/heads/foo.lock/bar"}, "ck_project_repository_bindings_release_ref_prefix"),
        ({"release_ref_prefix": "refs/heads/foo/\u0001bar"}, "ck_project_repository_bindings_release_ref_prefix"),
        ({"time_order_invalid": True}, "ck_project_repository_bindings_time_order"),
    ],
)
def test_m7_binding_check_constraints_reject_invalid_rows(
    overrides: dict[str, Any],
    expected_constraint: str,
) -> None:
    """Binding CHECK 必须覆盖 provider、identity、配置和完整 Git ref 规则。"""

    values = dict(overrides)
    time_order_invalid = bool(values.pop("time_order_invalid", False))
    binding = _build_binding(_seed_project(), **values)
    if time_order_invalid:
        now = utc_now()
        binding.created_at = now
        binding.updated_at = now - timedelta(seconds=1)
    with Session(get_engine()) as session:
        _assert_constraint_violation(session, binding, expected_constraint)


@pytest.mark.parametrize(
    "constraint_name",
    [
        "uq_project_repository_bindings_project",
        "uq_project_repository_bindings_external",
        "ux_project_repository_bindings_owner_name",
    ],
)
def test_m7_binding_unique_constraints_reject_duplicates(
    constraint_name: str,
) -> None:
    """Binding 的 Project、外部 ID 与大小写不敏感 identity 必须真实唯一。"""

    first_project_id = _seed_project()
    second_project_id = (
        first_project_id
        if constraint_name == "uq_project_repository_bindings_project"
        else _seed_project()
    )
    first = _build_binding(first_project_id, suffix=uuid4().hex[:12])
    second = _build_binding(second_project_id, suffix=uuid4().hex[:12])
    if constraint_name == "uq_project_repository_bindings_external":
        second.repository_external_id = first.repository_external_id
    elif constraint_name == "ux_project_repository_bindings_owner_name":
        second.repository_owner = first.repository_owner.upper()
        second.repository_name = first.repository_name.upper()

    with Session(get_engine()) as session:
        session.add(first)
        session.flush()
        _assert_constraint_violation(session, second, constraint_name)


@pytest.mark.parametrize(
    ("case_name", "expected_constraint"),
    [
        (
            "invalid_status",
            {
                "ck_release_candidates_status",
                "ck_release_candidates_lifecycle",
            },
        ),
        ("missing_snapshot_key", "ck_release_candidates_snapshot"),
        ("extra_snapshot_key", "ck_release_candidates_snapshot"),
        ("snapshot_number", "ck_release_candidates_snapshot"),
        ("snapshot_hidden_ref", "ck_release_candidates_snapshot"),
        ("snapshot_lock_component", "ck_release_candidates_snapshot"),
        ("snapshot_control_character", "ck_release_candidates_snapshot"),
        ("invalid_snapshot_hash", "ck_release_candidates_snapshot_hash"),
        ("invalid_commit_sha", "ck_release_candidates_commit_sha"),
        (
            "invalid_remote_sha",
            {
                "ck_release_candidates_remote_sha",
                "ck_release_candidates_lifecycle",
            },
        ),
        ("invalid_request_hash", "ck_release_candidates_request_hash"),
        ("empty_idempotency_key", "ck_release_candidates_idempotency_key"),
        ("hidden_target_ref", "ck_release_candidates_target_ref"),
        ("lock_target_ref_component", "ck_release_candidates_target_ref"),
        ("control_target_ref", "ck_release_candidates_target_ref"),
        ("pending_has_approved_at", "ck_release_candidates_lifecycle"),
        ("published_remote_mismatch", "ck_release_candidates_lifecycle"),
        ("approved_before_created", "ck_release_candidates_time_order"),
    ],
)
def test_m7_candidate_check_constraints_reject_invalid_rows(
    m7_references: dict[str, Any],
    case_name: str,
    expected_constraint: str | set[str],
) -> None:
    """Candidate 每类格式、snapshot、状态和时间门禁必须真实拒绝写入。"""

    now = utc_now()
    overrides: dict[str, Any] = {}
    snapshot = valid_binding_snapshot()
    if case_name == "invalid_status":
        overrides["status"] = "publishing"
    elif case_name == "missing_snapshot_key":
        snapshot.pop("workflow_id")
        overrides["binding_snapshot_json"] = snapshot
    elif case_name == "extra_snapshot_key":
        snapshot["credential_ref"] = "secret"
        overrides["binding_snapshot_json"] = snapshot
    elif case_name == "snapshot_number":
        snapshot["repository_owner"] = 123
        overrides["binding_snapshot_json"] = snapshot
    elif case_name == "snapshot_hidden_ref":
        snapshot["release_ref_prefix"] = "refs/heads/.hidden"
        overrides["binding_snapshot_json"] = snapshot
    elif case_name == "snapshot_lock_component":
        snapshot["release_ref_prefix"] = "refs/heads/foo.lock/bar"
        overrides["binding_snapshot_json"] = snapshot
    elif case_name == "snapshot_control_character":
        snapshot["release_ref_prefix"] = "refs/heads/foo/\u0001bar"
        overrides["binding_snapshot_json"] = snapshot
    elif case_name == "invalid_snapshot_hash":
        overrides["binding_snapshot_sha256"] = "sha256:ABC"
    elif case_name == "invalid_commit_sha":
        overrides["commit_sha"] = "1" * 39
    elif case_name == "invalid_remote_sha":
        overrides.update(
            {
                "status": "published",
                "approved_at": now,
                "published_at": now,
                "remote_verified_sha": "2" * 39,
            }
        )
    elif case_name == "invalid_request_hash":
        overrides["request_hash"] = "sha256:ABC"
    elif case_name == "empty_idempotency_key":
        overrides["idempotency_key"] = ""
    elif case_name == "hidden_target_ref":
        overrides["target_ref"] = "refs/heads/.hidden"
    elif case_name == "lock_target_ref_component":
        overrides["target_ref"] = "refs/heads/foo.lock/bar"
    elif case_name == "control_target_ref":
        overrides["target_ref"] = "refs/heads/foo/\u0001bar"
    elif case_name == "pending_has_approved_at":
        overrides["approved_at"] = now
    elif case_name == "published_remote_mismatch":
        overrides.update(
            {
                "status": "published",
                "approved_at": now,
                "published_at": now,
                "remote_verified_sha": "2" * 40,
            }
        )
    else:
        overrides.update(
            {
                "status": "approved",
                "created_at": now,
                "updated_at": now,
                "approved_at": now - timedelta(seconds=1),
            }
        )

    with Session(get_engine()) as session:
        _assert_constraint_violation(
            session,
            build_release_candidate(m7_references, **overrides),
            expected_constraint,
        )


@pytest.mark.parametrize(
    "status",
    [
        "pending_approval",
        "approved",
        "rejected",
        "published",
        "stale",
        "cancelled",
    ],
)
def test_m7_candidate_lifecycle_accepts_valid_rows(
    m7_references: dict[str, Any],
    status: str,
) -> None:
    """Candidate 每个数据库状态分支都必须存在一条可写入的合法形态。"""

    now = utc_now()
    overrides: dict[str, Any] = {
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    if status == "approved":
        overrides["approved_at"] = now
    elif status == "published":
        overrides.update(
            {
                "approved_at": now,
                "published_at": now,
                "remote_verified_sha": "1" * 40,
            }
        )

    with Session(get_engine()) as session:
        session.add(build_release_candidate(m7_references, **overrides))
        session.flush()
        session.rollback()


@pytest.mark.parametrize(
    "constraint_name",
    [
        "uq_release_candidates_task_idempotency",
        "uq_release_candidates_binding_ref",
        "uq_release_candidates_pr_snapshot",
        "ux_release_candidates_approval",
        "ux_release_candidates_task_active",
    ],
)
def test_m7_candidate_unique_constraints_reject_duplicates(
    m7_references: dict[str, Any],
    constraint_name: str,
) -> None:
    """Candidate 三个 UNIQUE 与两个部分唯一索引必须命中准确约束。"""

    first_id = uuid4()
    second_id = uuid4()
    active_time = utc_now()
    with Session(get_engine()) as session:
        second_approval = build_release_candidate_approval(
            task_id=m7_references["task_id"],
            requested_by_agent_run_id=m7_references["creator_agent_run_id"],
            candidate_id=second_id,
            request_hash="sha256:" + ("9" * 64),
        )
        session.add(second_approval)
        session.flush()
        first = build_release_candidate(
            m7_references,
            id=first_id,
            status=(
                "pending_approval"
                if constraint_name == "ux_release_candidates_task_active"
                else "rejected"
            ),
            target_ref=f"refs/heads/cloudhelm/release-candidates/{first_id.hex}",
            idempotency_key=f"candidate:{first_id}",
        )
        second = build_release_candidate(
            m7_references,
            id=second_id,
            approval_id=second_approval.id,
            pull_request_record_id=m7_references["pull_request_record_ids"][0],
            binding_snapshot_sha256="sha256:" + ("8" * 64),
            target_ref=f"refs/heads/cloudhelm/release-candidates/{second_id.hex}",
            idempotency_key=f"candidate:{second_id}",
            status=(
                "approved"
                if constraint_name == "ux_release_candidates_task_active"
                else "rejected"
            ),
            approved_at=(
                active_time
                if constraint_name == "ux_release_candidates_task_active"
                else None
            ),
        )
        if constraint_name == "ux_release_candidates_task_active":
            second.created_at = active_time
            second.updated_at = active_time
        if constraint_name == "uq_release_candidates_task_idempotency":
            second.idempotency_key = first.idempotency_key
        elif constraint_name == "uq_release_candidates_binding_ref":
            second.target_ref = first.target_ref
        elif constraint_name == "uq_release_candidates_pr_snapshot":
            second.pull_request_record_id = first.pull_request_record_id
            second.binding_snapshot_sha256 = first.binding_snapshot_sha256
        elif constraint_name == "ux_release_candidates_approval":
            second.approval_id = first.approval_id

        session.add(first)
        session.flush()
        _assert_constraint_violation(session, second, constraint_name)


@pytest.mark.parametrize(
    ("case_name", "expected_constraint"),
    [
        ("wrong_handler", "ck_workflow_jobs_m7_2_handler"),
        (
            "invalid_status",
            {
                "ck_workflow_jobs_status",
                "ck_workflow_jobs_lifecycle",
            },
        ),
        ("invalid_request_hash", "ck_workflow_jobs_request_hash"),
        ("empty_idempotency_key", "ck_workflow_jobs_idempotency_key"),
        ("negative_attempt", "ck_workflow_jobs_attempts"),
        ("payload_array", "ck_workflow_jobs_payload_object"),
        ("result_array", "ck_workflow_jobs_result_object"),
        ("worker_lease_pair", "ck_workflow_jobs_worker_lease_pair"),
        ("dispatch_lease_pair", "ck_workflow_jobs_dispatch_lease_pair"),
        ("dispatch_on_claimed", "ck_workflow_jobs_dispatch_lease_status"),
        ("retry_after_enqueue", "ck_workflow_jobs_retry_enqueue"),
        ("negative_enqueue_attempt", "ck_workflow_jobs_enqueue_attempt"),
        ("pending_attempt_exhausted", "ck_workflow_jobs_lifecycle"),
        ("pending_has_cancel_time", "ck_workflow_jobs_cancel"),
        ("succeeded_without_result", "ck_workflow_jobs_result_semantics"),
        ("updated_before_created", "ck_workflow_jobs_time_order"),
    ],
)
def test_m7_workflow_job_check_constraints_reject_invalid_rows(
    m7_references: dict[str, Any],
    case_name: str,
    expected_constraint: str | set[str],
) -> None:
    """WorkflowJob handler、lease、retry、生命周期和结果语义必须落库拒绝。"""

    now = utc_now()
    overrides: dict[str, Any] = {
        "resource_id": uuid4(),
        "idempotency_key": f"reconcile:{uuid4()}",
    }
    if case_name == "wrong_handler":
        overrides["job_type"] = "publish_release_candidate"
    elif case_name == "invalid_status":
        overrides["status"] = "queued"
    elif case_name == "invalid_request_hash":
        overrides["request_hash"] = "sha256:ABC"
    elif case_name == "empty_idempotency_key":
        overrides["idempotency_key"] = ""
    elif case_name == "negative_attempt":
        overrides["attempt"] = -1
    elif case_name == "payload_array":
        overrides["payload_json"] = []
    elif case_name == "result_array":
        overrides["result_json"] = []
    elif case_name == "worker_lease_pair":
        overrides.update(
                {
                    "status": "claimed",
                    "lease_owner": "worker-1",
                    "heartbeat_at": now,
                    "next_enqueue_at": null(),
                    "created_at": now,
                    "updated_at": now,
                }
            )
    elif case_name == "dispatch_lease_pair":
        overrides["dispatch_lease_owner"] = "dispatcher-1"
    elif case_name == "dispatch_on_claimed":
        overrides.update(
            {
                "status": "claimed",
                "lease_owner": "worker-1",
                "lease_expires_at": now + timedelta(minutes=1),
                "heartbeat_at": now,
                "dispatch_lease_owner": "dispatcher-1",
                    "dispatch_lease_expires_at": now + timedelta(minutes=1),
                    "next_enqueue_at": null(),
                    "created_at": now,
                    "updated_at": now,
                }
            )
    elif case_name == "retry_after_enqueue":
        overrides.update(
            {
                "next_retry_at": now + timedelta(minutes=2),
                "next_enqueue_at": now + timedelta(minutes=1),
            }
        )
    elif case_name == "negative_enqueue_attempt":
        overrides["enqueue_attempt"] = -1
    elif case_name == "pending_attempt_exhausted":
        overrides.update({"attempt": 3, "max_attempts": 3})
    elif case_name == "pending_has_cancel_time":
        overrides["cancel_requested_at"] = now
    elif case_name == "succeeded_without_result":
        overrides.update(
            {
                "status": "succeeded",
                "finished_at": now,
                "next_enqueue_at": null(),
            }
        )
    else:
        overrides.update(
            {
                "created_at": now,
                "updated_at": now - timedelta(seconds=1),
            }
        )

    with Session(get_engine()) as session:
        _assert_constraint_violation(
            session,
            build_workflow_job(m7_references, **overrides),
            expected_constraint,
        )


@pytest.mark.parametrize(
    "status",
    [
        "pending",
        "claimed",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
        "recovery_required",
    ],
)
def test_m7_workflow_job_lifecycle_accepts_valid_rows(
    m7_references: dict[str, Any],
    status: str,
) -> None:
    """WorkflowJob 每个 lifecycle 分支都必须存在一条可持久化的合法形态。"""

    now = utc_now()
    overrides: dict[str, Any] = {
        "resource_id": uuid4(),
        "idempotency_key": f"reconcile:{uuid4()}",
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    if status in {"claimed", "running", "cancel_requested"}:
        overrides.update(
            {
                "attempt": 1,
                "lease_owner": "worker-1",
                "lease_expires_at": now + timedelta(minutes=1),
                "heartbeat_at": now,
                "next_enqueue_at": null(),
            }
        )
    if status in {"running", "cancel_requested"}:
        overrides["started_at"] = now
    if status == "cancel_requested":
        overrides["cancel_requested_at"] = now
    elif status == "succeeded":
        overrides.update(
            {
                "finished_at": now,
                "result_json": {"outcome": "valid"},
                "next_enqueue_at": null(),
            }
        )
    elif status == "failed":
        overrides.update(
            {
                "finished_at": now,
                "error_code": "workflow_failed",
                "next_enqueue_at": null(),
            }
        )
    elif status == "cancelled":
        overrides.update(
            {
                "finished_at": now,
                "cancel_requested_at": now,
                "error_code": "workflow_cancelled",
                "next_enqueue_at": null(),
            }
        )
    elif status == "recovery_required":
        overrides.update(
            {
                "error_code": "workflow_recovery_required",
                "next_enqueue_at": null(),
            }
        )

    with Session(get_engine()) as session:
        session.add(build_workflow_job(m7_references, **overrides))
        session.flush()
        session.rollback()


def test_m7_workflow_job_unique_constraints_reject_duplicates(
    m7_references: dict[str, Any],
) -> None:
    """WorkflowJob 的幂等唯一和 blocking resource 部分唯一均需行为验证。"""

    with Session(get_engine()) as session:
        first_resource_id = uuid4()
        first = build_workflow_job(
            m7_references,
            resource_id=first_resource_id,
            idempotency_key="reconcile:duplicate-idempotency",
        )
        second = build_workflow_job(
            m7_references,
            resource_id=uuid4(),
            idempotency_key="reconcile:duplicate-idempotency",
        )
        session.add(first)
        session.flush()
        _assert_constraint_violation(
            session,
            second,
            "uq_workflow_jobs_task_type_idempotency",
        )

    with Session(get_engine()) as session:
        blocking_resource_id = uuid4()
        first = build_workflow_job(
            m7_references,
            resource_id=blocking_resource_id,
            idempotency_key=f"reconcile:{uuid4()}",
        )
        second = build_workflow_job(
            m7_references,
            resource_id=blocking_resource_id,
            idempotency_key=f"reconcile:{uuid4()}",
        )
        session.add(first)
        session.flush()
        _assert_constraint_violation(
            session,
            second,
            "ux_workflow_jobs_blocking_resource",
        )


def test_m7_candidate_foreign_keys_prevent_parent_deletion(
    m7_references: dict[str, Any],
) -> None:
    """Candidate 的 Binding 与 Approval NO ACTION 外键必须真实阻断单独删除。"""

    with Session(get_engine()) as session:
        session.add(build_release_candidate(m7_references))
        session.flush()
        for table_name, identity_key, expected_constraint in (
            (
                "project_repository_bindings",
                "repository_binding_id",
                "release_candidates_repository_binding_id_fkey",
            ),
            (
                "approval_requests",
                "approval_id",
                "release_candidates_approval_id_fkey",
            ),
        ):
            with pytest.raises(IntegrityError) as exc_info:
                with session.begin_nested():
                    session.execute(
                        text(f"DELETE FROM {table_name} WHERE id = :id"),
                        {"id": m7_references[identity_key]},
                    )
                    session.flush()
            assert _constraint_name(exc_info.value) == expected_constraint
        session.rollback()


def test_m7_task_delete_cascades_candidate_approval_and_workflow(
    m7_references: dict[str, Any],
) -> None:
    """删除 Task 必须清理任务资源，同时保留 Project 级 RepositoryBinding。"""

    with Session(get_engine()) as session:
        candidate = build_release_candidate(m7_references)
        session.add(candidate)
        session.flush()
        session.add(
            build_workflow_job(
                m7_references,
                resource_id=candidate.id,
            )
        )
        session.commit()

    with Session(get_engine()) as session:
        session.execute(
            text("DELETE FROM tasks WHERE id = :task_id"),
            {"task_id": m7_references["task_id"]},
        )
        session.commit()

    with get_engine().connect() as connection:
        remaining = connection.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM tasks WHERE id = :task_id) AS tasks,
                  (
                    SELECT count(*) FROM approval_requests
                    WHERE id = :approval_id
                  ) AS approvals,
                  (
                    SELECT count(*) FROM release_candidates
                    WHERE id = :candidate_id
                  ) AS candidates,
                  (
                    SELECT count(*) FROM workflow_jobs
                    WHERE resource_id = :candidate_id
                  ) AS jobs,
                  (
                    SELECT count(*) FROM project_repository_bindings
                    WHERE id = :binding_id
                  ) AS bindings
                """
            ),
            {
                "task_id": m7_references["task_id"],
                "approval_id": m7_references["approval_id"],
                "candidate_id": m7_references["candidate_id"],
                "binding_id": m7_references["repository_binding_id"],
            },
        ).one()

    assert remaining.tasks == 0
    assert remaining.approvals == 0
    assert remaining.candidates == 0
    assert remaining.jobs == 0
    assert remaining.bindings == 1


def test_m7_project_delete_cascades_repository_binding() -> None:
    """删除 Project 必须级联删除未被 Candidate 引用的 RepositoryBinding。"""

    project_id = _seed_project()
    with Session(get_engine(), expire_on_commit=False) as session:
        binding = _build_binding(project_id)
        session.add(binding)
        session.commit()
        binding_id = binding.id

    with Session(get_engine()) as session:
        session.execute(
            text("DELETE FROM projects WHERE id = :project_id"),
            {"project_id": project_id},
        )
        session.commit()

    with get_engine().connect() as connection:
        remaining = connection.execute(
            text(
                """
                SELECT count(*)
                FROM project_repository_bindings
                WHERE id = :binding_id
                """
            ),
            {"binding_id": binding_id},
        ).scalar_one()
    assert remaining == 0


def test_m7_database_server_defaults_are_effective(
    m7_references: dict[str, Any],
) -> None:
    """0008 的关键默认值必须由 PostgreSQL 自身生成，而非只依赖 ORM。"""

    candidate_id = uuid4()
    connection = get_engine().connect()
    transaction = connection.begin()
    try:
        binding_row = connection.execute(
            text(
                """
                INSERT INTO project_repository_bindings (
                    id, project_id, profile_key, repository_external_id,
                    repository_owner, repository_name, clone_url,
                    default_branch, credential_ref, workflow_id,
                    release_ref_prefix
                )
                VALUES (
                    :id, :project_id, :profile_key, :repository_external_id,
                    :repository_owner, :repository_name, :clone_url,
                    'main', :credential_ref,
                    '.gitea/workflows/cloudhelm-release.yml',
                    'refs/heads/cloudhelm/release-candidates'
                )
                RETURNING provider, status, created_at, updated_at
                """
            ),
            {
                "id": uuid4(),
                "project_id": _seed_project(),
                "profile_key": f"profile-{uuid4().hex[:12]}",
                "repository_external_id": f"repo-{uuid4().hex[:12]}",
                "repository_owner": f"owner-{uuid4().hex[:12]}",
                "repository_name": f"service-{uuid4().hex[:12]}",
                "clone_url": (
                    f"https://gitea.example.test/{uuid4().hex}/repo.git"
                ),
                "credential_ref": f"credential:m7:{uuid4().hex}",
            },
        ).one()
        assert binding_row.provider == "gitea"
        assert binding_row.status == "active"
        assert binding_row.created_at is not None
        assert binding_row.updated_at is not None

        candidate_row = connection.execute(
            text(
                """
                INSERT INTO release_candidates (
                    id, task_id, project_id, pull_request_record_id,
                    repository_binding_id, binding_snapshot_json,
                    binding_snapshot_sha256, commit_sha, target_ref,
                    request_hash, approval_id, idempotency_key
                )
                VALUES (
                    :id, :task_id, :project_id, :pull_request_record_id,
                    :repository_binding_id, CAST(:snapshot AS jsonb),
                    :snapshot_hash, :commit_sha, :target_ref,
                    :request_hash, :approval_id, :idempotency_key
                )
                RETURNING status, created_at, updated_at
                """
            ),
            {
                "id": candidate_id,
                "task_id": m7_references["task_id"],
                "project_id": m7_references["project_id"],
                "pull_request_record_id": m7_references[
                    "pull_request_record_id"
                ],
                "repository_binding_id": m7_references[
                    "repository_binding_id"
                ],
                "snapshot": (
                    '{"schema_version":"m7.repository-binding.snapshot.v1",'
                    '"provider":"gitea",'
                    '"repository_external_id":"repo-default-test",'
                    '"repository_owner":"cloudhelm",'
                    '"repository_name":"sample-service",'
                    '"default_branch":"main",'
                    '"workflow_id":".gitea/workflows/cloudhelm-release.yml",'
                    '"release_ref_prefix":'
                    '"refs/heads/cloudhelm/release-candidates"}'
                ),
                "snapshot_hash": "sha256:" + ("6" * 64),
                "commit_sha": "3" * 40,
                "target_ref": (
                    "refs/heads/cloudhelm/release-candidates/"
                    f"{candidate_id.hex}"
                ),
                "request_hash": "sha256:" + ("7" * 64),
                "approval_id": m7_references["approval_id"],
                "idempotency_key": f"candidate:{candidate_id}",
            },
        ).one()
        assert candidate_row.status == "pending_approval"
        assert candidate_row.created_at is not None
        assert candidate_row.updated_at is not None

        workflow_row = connection.execute(
            text(
                """
                INSERT INTO workflow_jobs (
                    id, task_id, job_type, resource_type, resource_id,
                    side_effect_class, request_hash, idempotency_key
                )
                VALUES (
                    :id, :task_id, 'release_candidate_reconcile',
                    'release_candidate', :resource_id, 'none',
                    :request_hash, :idempotency_key
                )
                RETURNING
                    status, attempt, max_attempts, enqueue_attempt,
                    payload_json, next_enqueue_at, created_at, updated_at
                """
            ),
            {
                "id": uuid4(),
                "task_id": m7_references["task_id"],
                "resource_id": candidate_id,
                "request_hash": "sha256:" + ("5" * 64),
                "idempotency_key": f"reconcile:{candidate_id}",
            },
        ).one()
        assert workflow_row.status == "pending"
        assert workflow_row.attempt == 0
        assert workflow_row.max_attempts == 3
        assert workflow_row.enqueue_attempt == 0
        assert workflow_row.payload_json == {}
        assert workflow_row.next_enqueue_at is not None
        assert workflow_row.created_at is not None
        assert workflow_row.updated_at is not None
    finally:
        transaction.rollback()
        connection.close()
