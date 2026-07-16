"""M7-2C release_candidate_reconcile 与 Task 生命周期集成测试。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.pull_request_record import (
    PullRequestRecord,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.repositories.project_repository_binding_repository import (
    ProjectRepositoryBindingRepository,
)
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.services.release_candidate_reconcile_service import (
    ReleaseCandidateReconcileService,
)
from cloudhelm_platform_api.services.release_candidate_approval_policy import (
    ReleaseCandidateApprovalPolicy,
)
from m7_release_candidate_api_fixture import (
    seed_release_candidate_dependencies,
)


def _create_candidate(client: TestClient) -> dict:
    references = seed_release_candidate_dependencies(client)
    response = client.post(
        f"/api/tasks/{references['task_id']}/release-candidate",
        json={},
    )
    assert response.status_code == 201, response.text
    return {
        **references,
        "candidate": response.json()["candidate"],
        "approval": response.json()["approval"],
    }


def _run_reconcile(candidate_id: str, *, owner: str = "worker:test"):
    candidate_uuid = UUID(candidate_id)
    with Session(get_engine()) as session:
        job = WorkflowJobRepository(session).get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_uuid,
        )
        assert job is not None
        job_id = job.id
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        assert repository.claim_job(
            job_id=job_id,
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        session.commit()
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        assert repository.mark_running(
            job_id=job_id,
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        session.commit()
    with Session(get_engine(), expire_on_commit=False) as session:
        job = ReleaseCandidateReconcileService(session).execute(
            workflow_job_id=job_id,
            worker_owner=owner,
        )
        session.commit()
        assert job is not None
        return job


def _claim_and_mark_running(
    candidate_id: str,
    *,
    owner: str,
    lease: timedelta,
) -> UUID:
    """使用真实独立事务把 Candidate job 推进到 running。"""

    candidate_uuid = UUID(candidate_id)
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        job = repository.get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_uuid,
        )
        assert job is not None
        job_id = job.id
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        assert repository.claim_job(
            job_id=job_id,
            worker_owner=owner,
            worker_lease=lease,
        )
        session.commit()
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        assert repository.mark_running(
            job_id=job_id,
            worker_owner=owner,
            worker_lease=lease,
        )
        session.commit()
    return job_id


def _execute_after_binding_wait(
    *,
    job_id: UUID,
    binding_id: UUID,
    owner: str,
    wait_seconds: float,
    monkeypatch,
):
    """持有 Binding 锁，确定性制造 Job 锁后的资源锁等待。"""

    blocker = Session(get_engine())
    locked = ProjectRepositoryBindingRepository(blocker).get(
        binding_id,
        for_update=True,
    )
    assert locked is not None
    waiting_on_binding = threading.Event()
    original_get = ProjectRepositoryBindingRepository.get

    def observed_get(
        repository,
        requested_binding_id,
        *,
        for_update: bool = False,
    ):
        if for_update and requested_binding_id == binding_id:
            waiting_on_binding.set()
        return original_get(
            repository,
            requested_binding_id,
            for_update=for_update,
        )

    monkeypatch.setattr(
        ProjectRepositoryBindingRepository,
        "get",
        observed_get,
    )

    def execute():
        with Session(get_engine(), expire_on_commit=False) as session:
            job = ReleaseCandidateReconcileService(session).execute(
                workflow_job_id=job_id,
                worker_owner=owner,
            )
            session.commit()
            return job

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(execute)
    try:
        try:
            assert waiting_on_binding.wait(timeout=10)
            time.sleep(wait_seconds)
        finally:
            blocker.commit()
        return future.result(timeout=10)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        blocker.rollback()
        blocker.close()


def test_reconcile_pending_candidate_succeeds_valid(
    client: TestClient,
) -> None:
    """pending/pending 且 freshness 一致时写严格 valid result。"""

    references = _create_candidate(client)

    job = _run_reconcile(references["candidate"]["id"])

    assert job.status == "succeeded"
    assert job.result_json["outcome"] == "valid"
    assert job.result_json["candidate_status"] == "pending_approval"
    assert job.result_json["approval_status"] == "pending"
    with Session(get_engine()) as session:
        event = session.scalar(
            select(EventLog).where(
                EventLog.event_type == "WorkflowJobSucceeded"
            )
        )
        assert event is not None
        assert event.payload["outcome"] == "valid"


def test_reconcile_approved_candidate_succeeds_valid(
    client: TestClient,
) -> None:
    """approved/approved 且 freshness 一致时仍为 valid。"""

    references = _create_candidate(client)
    response = client.post(
        f"/api/approvals/{references['approval']['id']}/approve",
        json={"actor_id": "reviewer:reconcile-valid"},
    )
    assert response.status_code == 200, response.text

    job = _run_reconcile(references["candidate"]["id"])

    assert job.status == "succeeded"
    assert job.result_json["outcome"] == "valid"
    assert job.result_json["candidate_status"] == "approved"
    assert job.result_json["approval_status"] == "approved"


def test_reconcile_binding_disabled_marks_candidate_stale(
    client: TestClient,
) -> None:
    """Binding freshness 漂移原子 stale Candidate/Approval 并成功收敛。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        binding = session.get(
            ProjectRepositoryBinding,
            UUID(references["repository_binding_id"]),
        )
        assert binding is not None
        binding.status = "disabled"
        session.commit()

    job = _run_reconcile(references["candidate"]["id"])

    assert job.status == "succeeded"
    assert job.result_json["outcome"] == "stale"
    assert job.result_json["candidate_status"] == "stale"
    assert job.result_json["approval_status"] == "expired"


def test_reconcile_active_candidate_with_expired_approval_is_stale(
    client: TestClient,
) -> None:
    """审批失效属于 freshness stale，不误报状态结构错误。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert approval is not None
        now = WorkflowJobRepository(session).database_now()
        approval.status = "expired"
        approval.decided_by = "system:test-expiry"
        approval.decided_at = max(now, approval.created_at)
        session.commit()

    job = _run_reconcile(references["candidate"]["id"])

    assert job.status == "succeeded"
    assert job.result_json["outcome"] == "stale"
    assert job.result_json["approval_status"] == "expired"


def test_reconcile_invalid_decision_pair_fails_without_repair(
    client: TestClient,
) -> None:
    """pending Candidate + approved Approval 是不可自动修复的状态异常。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert approval is not None
        now = WorkflowJobRepository(session).database_now()
        approval.status = "approved"
        approval.decided_by = "reviewer:test"
        approval.decided_at = max(now, approval.created_at)
        session.commit()

    job = _run_reconcile(references["candidate"]["id"])

    assert job.status == "failed"
    assert job.error_code == "release_candidate_approval_state_invalid"
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(references["candidate"]["id"]),
        )
        assert candidate is not None
        assert candidate.status == "pending_approval"


def test_reconcile_missing_payload_approval_fails_state_invalid(
    client: TestClient,
) -> None:
    """payload 指向不存在 Approval 时使用领域状态错误而非资源 404。"""

    references = _create_candidate(client)
    candidate_id = UUID(references["candidate"]["id"])
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        job = repository.get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_id,
            for_update=True,
        )
        assert job is not None
        job.payload_json = {
            **job.payload_json,
            "approval_id": "00000000-0000-4000-8000-000000000999",
        }
        session.commit()

    result = _run_reconcile(references["candidate"]["id"])

    assert result.status == "failed"
    assert (
        result.error_code
        == "release_candidate_approval_state_invalid"
    )


@pytest.mark.parametrize("drift", ["resource", "hash"])
def test_reconcile_approval_contract_drift_marks_candidate_stale(
    client: TestClient,
    drift: str,
) -> None:
    """数据库可持久化的 resource/hash 漂移统一安全 stale。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert approval is not None
        if drift == "resource":
            approval.resource_id = UUID(
                "00000000-0000-4000-8000-000000000998"
            )
        else:
            approval.request_hash = "sha256:" + ("f" * 64)
        session.commit()

    result = _run_reconcile(references["candidate"]["id"])

    assert result.status == "succeeded"
    assert result.result_json["outcome"] == "stale"
    assert result.result_json["candidate_status"] == "stale"
    assert result.result_json["approval_status"] == "expired"


def test_reconcile_policy_detects_action_contract_drift(
    client: TestClient,
) -> None:
    """DB CHECK 拒绝 action 漂移，纯策略仍保留防御性识别。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(references["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert candidate is not None
        assert approval is not None
        approval.action = "release_candidate.publish"
        assert not ReleaseCandidateApprovalPolicy(
            session
        ).reconcile_approval_contract_is_fresh(
            candidate=candidate,
            approval=approval,
        )
        session.rollback()


@pytest.mark.parametrize(
    "drift",
    ["candidate_request_hash", "binding_snapshot_hash", "pull_request"],
)
def test_reconcile_frozen_candidate_identity_drift_is_stale(
    client: TestClient,
    drift: str,
) -> None:
    """Candidate 创建后 hash/snapshot/PR 漂移属于 freshness stale。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(references["candidate"]["id"]),
        )
        assert candidate is not None
        if drift == "candidate_request_hash":
            candidate.request_hash = "sha256:" + ("d" * 64)
        elif drift == "binding_snapshot_hash":
            candidate.binding_snapshot_sha256 = (
                "sha256:" + ("e" * 64)
            )
        else:
            pull_request = session.get(
                PullRequestRecord,
                UUID(references["pull_request_record_id"]),
            )
            assert pull_request is not None
            pull_request.status = "closed"
        session.commit()

    result = _run_reconcile(references["candidate"]["id"])

    assert result.status == "succeeded"
    assert result.result_json["outcome"] == "stale"
    assert result.result_json["candidate_status"] == "stale"
    assert result.result_json["approval_status"] == "expired"


def test_reconcile_consumed_approval_marks_candidate_stale(
    client: TestClient,
) -> None:
    """已消费 Approval 保留 approved 历史，Candidate 收敛 stale。"""

    references = _create_candidate(client)
    response = client.post(
        f"/api/approvals/{references['approval']['id']}/approve",
        json={"actor_id": "reviewer:consumed"},
    )
    assert response.status_code == 200, response.text
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert approval is not None
        assert approval.decided_at is not None
        approval.consumed_at = approval.decided_at + timedelta(seconds=1)
        session.commit()

    result = _run_reconcile(references["candidate"]["id"])

    assert result.status == "succeeded"
    assert result.result_json["outcome"] == "stale"
    assert result.result_json["candidate_status"] == "stale"
    assert result.result_json["approval_status"] == "approved"


def test_reconcile_tampered_job_payload_fails_identity(
    client: TestClient,
) -> None:
    """payload 与持久化 job hash/idempotency 不一致时拒绝共同篡改。"""

    references = _create_candidate(client)
    candidate_id = UUID(references["candidate"]["id"])
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        job = repository.get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_id,
            for_update=True,
        )
        assert job is not None
        job.payload_json = {
            **job.payload_json,
            "expected_candidate_request_hash": (
                "sha256:" + ("f" * 64)
            ),
        }
        session.commit()

    result = _run_reconcile(references["candidate"]["id"])

    assert result.status == "failed"
    assert result.error_code == "release_candidate_job_identity_invalid"


def test_reconcile_rejected_candidate_is_terminal_noop(
    client: TestClient,
) -> None:
    """合法 rejected/rejected 历史只返回 terminal_noop。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(references["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert candidate is not None
        assert approval is not None
        now = WorkflowJobRepository(session).database_now()
        candidate.status = "rejected"
        candidate.updated_at = max(now, candidate.created_at)
        approval.status = "rejected"
        approval.decided_by = "reviewer:test"
        approval.decided_at = max(now, approval.created_at)
        session.commit()

    job = _run_reconcile(references["candidate"]["id"])

    assert job.status == "succeeded"
    assert job.result_json["outcome"] == "terminal_noop"
    assert job.result_json["candidate_status"] == "rejected"


@pytest.mark.parametrize(
    ("candidate_status", "approval_status"),
    [
        ("published", "approved"),
        ("stale", "expired"),
        ("cancelled", "expired"),
    ],
)
def test_reconcile_other_terminal_pairs_are_noop(
    client: TestClient,
    candidate_status: str,
    approval_status: str,
) -> None:
    """published/stale/cancelled 合法历史不会被 worker 改写。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(references["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert candidate is not None
        assert approval is not None
        now = WorkflowJobRepository(session).database_now()
        decision_time = max(now, approval.created_at)
        approval.status = approval_status
        approval.decided_by = "reviewer:terminal-history"
        approval.decided_at = decision_time
        candidate.status = candidate_status
        candidate.updated_at = max(decision_time, candidate.created_at)
        if candidate_status == "published":
            candidate.approved_at = decision_time
            candidate.published_at = decision_time + timedelta(seconds=1)
            candidate.remote_verified_sha = candidate.commit_sha
            candidate.updated_at = candidate.published_at
        session.commit()

    result = _run_reconcile(references["candidate"]["id"])

    assert result.status == "succeeded"
    assert result.result_json["outcome"] == "terminal_noop"
    assert result.result_json["candidate_status"] == candidate_status
    assert result.result_json["approval_status"] == approval_status


def test_task_cancel_closes_candidate_approval_and_pending_job(
    client: TestClient,
) -> None:
    """Task cancel 不遗留 active Candidate 或 pending WorkflowJob。"""

    references = _create_candidate(client)

    response = client.post(
        f"/api/tasks/{references['task_id']}/cancel",
        json={"actor_id": "operator:test", "reason": "取消发布"},
    )

    assert response.status_code == 200, response.text
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(references["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        job = WorkflowJobRepository(session).get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=UUID(references["candidate"]["id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert job is not None
        assert candidate.status == "cancelled"
        assert approval.status == "expired"
        assert job.status == "cancelled"
        event_types = set(
            session.scalars(
                select(EventLog.event_type).where(
                    EventLog.task_id == UUID(references["task_id"])
                )
            )
        )
        assert "WorkflowJobCancelled" in event_types
        assert "ReleaseCandidateCancelled" in event_types


def test_task_resume_preserves_future_workflow_retry_backoff(
    client: TestClient,
) -> None:
    """resume 唤醒普通 pending job，但不绕过未来 next_retry_at。"""

    references = _create_candidate(client)
    candidate_id = UUID(references["candidate"]["id"])
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        job = repository.get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_id,
            for_update=True,
        )
        assert job is not None
        now = repository.database_now()
        future_retry = now + timedelta(minutes=10)
        job.next_retry_at = future_retry
        job.next_enqueue_at = future_retry + timedelta(minutes=1)
        job.updated_at = max(now, job.created_at)
        session.commit()
        job_id = job.id

    pause = client.post(
        f"/api/tasks/{references['task_id']}/pause",
        json={"actor_id": "operator:test"},
    )
    assert pause.status_code == 200, pause.text
    resume = client.post(
        f"/api/tasks/{references['task_id']}/resume",
        json={"actor_id": "operator:test"},
    )
    assert resume.status_code == 200, resume.text

    with Session(get_engine()) as session:
        job = WorkflowJobRepository(session).get(job_id)
        assert job is not None
        assert job.next_retry_at == future_retry
        assert job.next_enqueue_at == future_retry


def test_reconcile_rechecks_worker_lease_after_binding_lock_wait(
    client: TestClient,
    monkeypatch,
) -> None:
    """资源锁等待跨过 lease 时不得用锁前时间提交旧 owner 结果。"""

    references = _create_candidate(client)
    owner = "worker:lease-expiry-race"
    job_id = _claim_and_mark_running(
        references["candidate"]["id"],
        owner=owner,
        lease=timedelta(milliseconds=300),
    )

    result = _execute_after_binding_wait(
        job_id=job_id,
        binding_id=UUID(references["repository_binding_id"]),
        owner=owner,
        wait_seconds=0.45,
        monkeypatch=monkeypatch,
    )

    assert result is None
    with Session(get_engine()) as session:
        repository = WorkflowJobRepository(session)
        job = repository.get(job_id)
        assert job is not None
        assert job.status == "running"
        recovered = repository.reclaim_stale_job(
            job_id=job_id,
            retry_backoff=timedelta(seconds=1),
            max_retry_backoff=timedelta(seconds=1),
        )
        session.commit()
        assert recovered is not None
        assert recovered.status == "pending"


def test_reconcile_rechecks_approval_expiry_after_binding_lock_wait(
    client: TestClient,
    monkeypatch,
) -> None:
    """资源锁等待期间到期的 Approval 必须按锁后数据库时间 stale。"""

    references = _create_candidate(client)
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(references["approval"]["id"]),
        )
        assert approval is not None
        now = WorkflowJobRepository(session).database_now()
        approval.expires_at = now + timedelta(milliseconds=300)
        session.commit()
    owner = "worker:approval-expiry-race"
    job_id = _claim_and_mark_running(
        references["candidate"]["id"],
        owner=owner,
        lease=timedelta(seconds=5),
    )

    result = _execute_after_binding_wait(
        job_id=job_id,
        binding_id=UUID(references["repository_binding_id"]),
        owner=owner,
        wait_seconds=0.45,
        monkeypatch=monkeypatch,
    )

    assert result is not None
    assert result.status == "succeeded"
    assert result.result_json["outcome"] == "stale"
    assert result.result_json["candidate_status"] == "stale"
    assert result.result_json["approval_status"] == "expired"
