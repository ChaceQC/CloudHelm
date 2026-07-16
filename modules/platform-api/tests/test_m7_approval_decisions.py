"""M7-2B2 Candidate 第一审批的领域门禁与并发测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.task import Task
from m7_release_candidate_api_fixture import (
    create_new_open_pull_request,
    seed_release_candidate_dependencies,
)

DECISION_EVENT_FIELDS = {
    "candidate_id",
    "approval_id",
    "pull_request_record_id",
    "repository_binding_id",
    "binding_snapshot_sha256",
    "candidate_request_hash",
    "status",
    "reason",
}


@pytest.mark.parametrize(
    ("operation", "expected_status", "event_type"),
    [
        ("approve", "approved", "ReleaseCandidateApproved"),
        ("reject", "rejected", "ReleaseCandidateRejected"),
    ],
)
def test_candidate_decision_updates_candidate_and_approval_atomically(
    client: TestClient,
    operation: str,
    expected_status: str,
    event_type: str,
) -> None:
    """approve/reject 共用数据库时间且不修改 Task 状态或阶段。"""

    seeded, envelope = _create_candidate(client)
    task_id = UUID(seeded["task_id"])
    with Session(get_engine()) as session:
        task = session.get(Task, task_id)
        assert task is not None
        task_state = (task.status, task.current_phase)

    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/{operation}",
        json={"actor_id": "reviewer-1", "reason": "M7 决策验证"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(envelope["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(envelope["approval"]["id"]),
        )
        task = session.get(Task, task_id)
        event = session.scalar(
            select(EventLog).where(
                EventLog.task_id == task_id,
                EventLog.event_type == event_type,
            )
        )
        assert candidate is not None
        assert approval is not None
        assert task is not None
        assert event is not None
        assert candidate.status == expected_status
        assert approval.status == expected_status
        assert approval.decided_by == "reviewer-1"
        assert approval.consumed_at is None
        assert (task.status, task.current_phase) == task_state
        if operation == "approve":
            assert candidate.approved_at == approval.decided_at
        else:
            assert candidate.approved_at is None
        assert set(event.payload) == DECISION_EVENT_FIELDS
        serialized = json.dumps(event.payload, sort_keys=True)
        assert "clone_url" not in serialized
        assert "credential_ref" not in serialized
        assert "profile_key" not in serialized


def test_rejected_candidate_post_remains_idempotent(
    client: TestClient,
) -> None:
    """rejected 后相同 PR/snapshot 仍返回原 Candidate，不创建新审批。"""

    seeded, envelope = _create_candidate(client)
    decision = client.post(
        f"/api/approvals/{envelope['approval']['id']}/reject",
        json={"actor_id": "reviewer", "reason": "需要新 commit"},
    )
    assert decision.status_code == 200

    repeated = client.post(
        f"/api/tasks/{seeded['task_id']}/release-candidate",
        json={},
    )

    assert repeated.status_code == 200
    assert repeated.json()["candidate"]["id"] == envelope["candidate"]["id"]
    assert repeated.json()["approval"]["id"] == envelope["approval"]["id"]
    assert repeated.json()["candidate"]["status"] == "rejected"


@pytest.mark.parametrize(
    "actor_template",
    [
        "{creator}",
        "agent-run:{creator}",
        "  agent-run:{creator}  ",
    ],
)
def test_candidate_creator_cannot_decide_own_approval(
    client: TestClient,
    actor_template: str,
) -> None:
    """plain/prefixed/trimmed AgentRun actor 均触发领域自批门禁。"""

    seeded, envelope = _create_candidate(client)
    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={
            "actor_id": actor_template.format(
                creator=seeded["creator_agent_run_id"]
            )
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "approval_self_decision_forbidden"
    _assert_pair_status(envelope, "pending_approval", "pending")


def test_candidate_decision_rejects_blank_actor(
    client: TestClient,
) -> None:
    """trim 后为空的 actor 不得进入审批审计字段。"""

    _seeded, envelope = _create_candidate(client)
    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={"actor_id": "   "},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_pair_status(envelope, "pending_approval", "pending")


def test_candidate_decision_redacts_secret_like_reason(
    client: TestClient,
) -> None:
    """审批事件与 conversation context 不保存 reason 中的凭据文本。"""

    seeded, envelope = _create_candidate(client)
    secret = "candidate-secret-value-123456"
    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={
            "actor_id": "reviewer",
            "reason": f"token={secret}",
        },
    )

    assert response.status_code == 200
    with Session(get_engine()) as session:
        events = list(
            session.scalars(
                select(EventLog).where(
                    EventLog.task_id == UUID(seeded["task_id"]),
                    EventLog.event_type.in_(
                        (
                            "ReleaseCandidateApproved",
                            "ApprovalApproved",
                        )
                    ),
                )
            )
        )
        serialized = json.dumps(
            [event.payload for event in events],
            ensure_ascii=False,
            sort_keys=True,
        )
        assert secret not in serialized
        assert "<redacted>" in serialized


def test_expired_approval_persists_candidate_stale(
    client: TestClient,
) -> None:
    """过期冲突返回前提交 Candidate stale 与 Approval expired。"""

    _seeded, envelope = _create_candidate(client)
    now = utc_now()
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(envelope["approval"]["id"]),
        )
        assert approval is not None
        approval.created_at = now - timedelta(hours=2)
        approval.expires_at = now - timedelta(hours=1)
        session.commit()

    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={"actor_id": "reviewer"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "approval_expired"
    _assert_pair_status(envelope, "stale", "expired")


def test_approval_request_hash_mismatch_stales_resources(
    client: TestClient,
) -> None:
    """Approval hash 被改写时提交 stale/expired 后返回稳定错误。"""

    _seeded, envelope = _create_candidate(client)
    with Session(get_engine()) as session:
        approval = session.get(
            ApprovalRequest,
            UUID(envelope["approval"]["id"]),
        )
        assert approval is not None
        approval.request_hash = "sha256:" + ("f" * 64)
        session.commit()

    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={"actor_id": "reviewer"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "approval_request_hash_mismatch"
    _assert_pair_status(envelope, "stale", "expired")


@pytest.mark.parametrize("drift_kind", ["binding", "pull_request"])
def test_candidate_freshness_drift_is_persisted(
    client: TestClient,
    drift_kind: str,
) -> None:
    """内部 Binding 或最新版 PR 漂移时原子 stale/expire。"""

    seeded, envelope = _create_candidate(client)
    if drift_kind == "binding":
        with Session(get_engine()) as session:
            binding = session.get(
                ProjectRepositoryBinding,
                UUID(seeded["repository_binding_id"]),
            )
            assert binding is not None
            binding.clone_url = (
                "https://gitea.example.test/CloudHelm/"
                "Sample-API-rotated.git"
            )
            session.commit()
    else:
        create_new_open_pull_request(seeded["task_id"])

    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={"actor_id": "reviewer"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "release_candidate_stale"
    _assert_pair_status(envelope, "stale", "expired")


def test_consumed_approval_error_takes_priority_over_repeat_decision(
    client: TestClient,
) -> None:
    """后续副作用消费后重复审批返回 approval_consumed。"""

    _seeded, envelope = _create_candidate(client)
    now = utc_now()
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(envelope["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(envelope["approval"]["id"]),
        )
        assert candidate is not None
        assert approval is not None
        decided_at = max(approval.created_at, now) + timedelta(seconds=1)
        candidate.status = "approved"
        candidate.approved_at = decided_at
        candidate.updated_at = decided_at
        approval.status = "approved"
        approval.decided_by = "reviewer"
        approval.decided_at = decided_at
        approval.consumed_at = decided_at + timedelta(seconds=1)
        session.commit()

    response = client.post(
        f"/api/approvals/{envelope['approval']['id']}/approve",
        json={"actor_id": "another-reviewer"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "approval_consumed"


def test_concurrent_approve_and_reject_produce_one_terminal_pair(
    client: TestClient,
) -> None:
    """并发相反决策只有一方成功，Candidate/Approval 不会分叉。"""

    _seeded, envelope = _create_candidate(client)
    approval_id = envelope["approval"]["id"]
    barrier = Barrier(2)

    def decide(operation: str) -> tuple[int, dict]:
        with TestClient(create_app()) as thread_client:
            barrier.wait(timeout=10)
            response = thread_client.post(
                f"/api/approvals/{approval_id}/{operation}",
                json={"actor_id": f"reviewer-{operation}"},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        approve_future = pool.submit(decide, "approve")
        reject_future = pool.submit(decide, "reject")
        results = [approve_future.result(), reject_future.result()]

    assert sorted(status for status, _payload in results) == [200, 409]
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(envelope["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(approval_id),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status in {"approved", "rejected"}
        assert approval.status == candidate.status


def _create_candidate(
    client: TestClient,
) -> tuple[dict[str, str], dict]:
    """准备依赖并通过真实 API 创建 Candidate。"""

    seeded = seed_release_candidate_dependencies(client)
    response = client.post(
        f"/api/tasks/{seeded['task_id']}/release-candidate",
        json={},
    )
    assert response.status_code == 201, response.text
    return seeded, response.json()


def _assert_pair_status(
    envelope: dict,
    candidate_status: str,
    approval_status: str,
) -> None:
    """断言 Candidate 与 Approval 的数据库终态保持一致。"""

    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(envelope["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(envelope["approval"]["id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == candidate_status
        assert approval.status == approval_status
