"""M7-2B1 RepositoryBinding 幂等与 Candidate 漂移测试。"""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from m7_repository_binding_fixture import (
    APPROVAL_EXPIRED_EVENT_FIELDS,
    event_count,
    seed_candidate,
)
from conftest import create_project


def test_identical_put_is_side_effect_free(
    client: TestClient,
) -> None:
    """相同 profile PUT 保留 ID、updated_at 和事件数量。"""

    project = create_project(client)
    path = f"/api/projects/{project['id']}/repository-binding"
    first = client.put(path, json={"profile_key": "test-primary"})
    assert first.status_code == 200
    configured_events = event_count("RepositoryBindingConfigured")

    second = client.put(path, json={"profile_key": "test-primary"})

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["created_at"] == first.json()["created_at"]
    assert second.json()["updated_at"] == first.json()["updated_at"]
    assert event_count("RepositoryBindingConfigured") == configured_events


def test_identical_put_does_not_invalidate_candidate_or_approval(
    client: TestClient,
) -> None:
    """幂等 PUT 对已有 Candidate/Approval 和其时间字段完全无副作用。"""

    seeded = seed_candidate(client, candidate_status="pending_approval")
    with Session(get_engine()) as session:
        before_candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        before_approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert before_candidate is not None
        assert before_approval is not None
        candidate_updated_at = before_candidate.updated_at
        approval_created_at = before_approval.created_at
    configured_events = event_count("RepositoryBindingConfigured")

    response = client.put(
        f"/api/projects/{seeded['project_id']}/repository-binding",
        json={"profile_key": "test-primary"},
    )

    assert response.status_code == 200
    assert event_count("RepositoryBindingConfigured") == configured_events
    assert event_count("ApprovalExpired") == 0
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == "pending_approval"
        assert candidate.updated_at == candidate_updated_at
        assert approval.status == "pending"
        assert approval.created_at == approval_created_at
        assert approval.decided_at is None


def test_binding_drift_stales_pending_candidate_and_expires_approval(
    client: TestClient,
) -> None:
    """内部 snapshot 漂移在同一事务失效 Candidate 与 pending Approval。"""

    seeded = seed_candidate(client, candidate_status="pending_approval")
    response = client.put(
        f"/api/projects/{seeded['project_id']}/repository-binding",
        json={"profile_key": "test-primary-drift"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["default_branch"] == "main"
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == "stale"
        assert approval.status == "expired"
        assert approval.decided_by == "system:release_candidate_freshness"
        assert approval.decided_at is not None
        expired_event = session.scalar(
            select(EventLog).where(
                EventLog.event_type == "ApprovalExpired",
                EventLog.task_id == UUID(seeded["task_id"]),
            )
        )
        assert expired_event is not None
        assert expired_event.actor_type == "system"
        assert (
            expired_event.actor_id
            == "system:release_candidate_freshness"
        )
        assert set(expired_event.payload) == APPROVAL_EXPIRED_EVENT_FIELDS
        assert expired_event.payload["approval_id"] == seeded["approval_id"]
        assert expired_event.payload["resource_id"] == seeded["candidate_id"]
        assert expired_event.payload["reason"] == "repository_binding_changed"


def test_disabled_binding_reactivation_invalidates_candidate(
    client: TestClient,
) -> None:
    """disabled -> active 即使 snapshot 相同也按真实配置漂移处理。"""

    seeded = seed_candidate(client, candidate_status="pending_approval")
    with Session(get_engine()) as session:
        binding = session.scalar(
            select(ProjectRepositoryBinding).where(
                ProjectRepositoryBinding.project_id
                == UUID(seeded["project_id"])
            )
        )
        assert binding is not None
        binding.status = "disabled"
        session.commit()

    response = client.put(
        f"/api/projects/{seeded['project_id']}/repository-binding",
        json={"profile_key": "test-primary"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == "stale"
        assert approval.status == "expired"


def test_internal_only_binding_drift_stales_candidate(
    client: TestClient,
) -> None:
    """Credential/profile 漂移即使 public snapshot 不变也会使 Candidate stale。"""

    seeded = seed_candidate(client, candidate_status="pending_approval")
    response = client.put(
        f"/api/projects/{seeded['project_id']}/repository-binding",
        json={"profile_key": "test-primary-secret-rotation"},
    )

    assert response.status_code == 200
    assert response.json()["default_branch"] == "dev"
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == "stale"
        assert approval.status == "expired"


def test_binding_drift_stales_approved_candidate_but_preserves_approval(
    client: TestClient,
) -> None:
    """Approved Candidate 变 stale，已批准 Approval 保留审计终态。"""

    seeded = seed_candidate(client, candidate_status="approved")
    response = client.put(
        f"/api/projects/{seeded['project_id']}/repository-binding",
        json={"profile_key": "test-primary-drift"},
    )

    assert response.status_code == 200
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == "stale"
        assert approval.status == "approved"
        assert approval.decided_by == "reviewer"


def test_binding_drift_preserves_published_candidate(
    client: TestClient,
) -> None:
    """Published Candidate 是历史终态，不参与 Binding 漂移失效。"""

    seeded = seed_candidate(client, candidate_status="published")
    response = client.put(
        f"/api/projects/{seeded['project_id']}/repository-binding",
        json={"profile_key": "test-primary-drift"},
    )

    assert response.status_code == 200
    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(seeded["candidate_id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(seeded["approval_id"]),
        )
        assert candidate is not None
        assert approval is not None
        assert candidate.status == "published"
        assert approval.status == "approved"
