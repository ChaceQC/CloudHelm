"""M7-2B2 ReleaseCandidate 创建、幂等与公开契约测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.main import app, create_app
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from m7_release_candidate_api_fixture import (
    create_new_open_pull_request,
    seed_release_candidate_dependencies,
)

CANDIDATE_FIELDS = {
    "id",
    "task_id",
    "project_id",
    "pull_request_record_id",
    "repository_binding_id",
    "binding_snapshot",
    "binding_snapshot_sha256",
    "commit_sha",
    "target_ref",
    "request_hash",
    "status",
    "approval_id",
    "remote_verified_sha",
    "idempotency_key",
    "approved_at",
    "published_at",
    "created_at",
    "updated_at",
}
SNAPSHOT_FIELDS = {
    "schema_version",
    "provider",
    "repository_external_id",
    "repository_owner",
    "repository_name",
    "default_branch",
    "workflow_id",
    "release_ref_prefix",
}
APPROVAL_FIELDS = {
    "id",
    "action",
    "risk_level",
    "resource_type",
    "resource_id",
    "status",
    "requested_by_agent_run_id",
    "request_hash",
    "expires_at",
    "consumed_at",
}
COMMON_EVENT_FIELDS = {
    "candidate_id",
    "approval_id",
    "workflow_job_id",
    "pull_request_record_id",
    "repository_binding_id",
    "binding_snapshot_sha256",
    "candidate_request_hash",
}
QUEUED_EVENT_FIELDS = COMMON_EVENT_FIELDS | {
    "job_type",
    "job_request_hash",
    "status",
}
REQUESTED_EVENT_FIELDS = COMMON_EVENT_FIELDS | {
    "action",
    "risk_level",
    "status",
}


def test_candidate_post_creates_atomic_resources_and_is_idempotent(
    client: TestClient,
) -> None:
    """首次 201、重复 200，三表与两类事件均只创建一次。"""

    seeded = seed_release_candidate_dependencies(client)
    path = f"/api/tasks/{seeded['task_id']}/release-candidate"

    first = client.post(path, json={})

    assert first.status_code == 201, first.text
    payload = first.json()
    assert set(payload) == {"candidate", "approval"}
    assert set(payload["candidate"]) == CANDIDATE_FIELDS
    assert set(payload["candidate"]["binding_snapshot"]) == SNAPSHOT_FIELDS
    assert set(payload["approval"]) == APPROVAL_FIELDS
    assert payload["candidate"]["task_id"] == seeded["task_id"]
    assert payload["candidate"]["project_id"] == seeded["project_id"]
    assert (
        payload["candidate"]["pull_request_record_id"]
        == seeded["pull_request_record_id"]
    )
    assert payload["candidate"]["status"] == "pending_approval"
    assert payload["approval"]["status"] == "pending"
    assert payload["approval"]["resource_id"] == payload["candidate"]["id"]
    assert (
        payload["approval"]["requested_by_agent_run_id"]
        == seeded["creator_agent_run_id"]
    )
    assert (
        payload["approval"]["request_hash"]
        == payload["candidate"]["request_hash"]
    )
    assert payload["candidate"]["target_ref"].endswith(
        payload["candidate"]["binding_snapshot_sha256"].removeprefix(
            "sha256:"
        )
    )

    second = client.post(path, json={})
    assert second.status_code == 200, second.text
    assert second.json() == payload
    get_response = client.get(path)
    assert get_response.status_code == 200
    assert get_response.json() == payload

    with Session(get_engine()) as session:
        candidate = session.get(
            ReleaseCandidate,
            UUID(payload["candidate"]["id"]),
        )
        approval = session.get(
            ApprovalRequest,
            UUID(payload["approval"]["id"]),
        )
        job = session.scalar(
            select(WorkflowJob).where(
                WorkflowJob.resource_id == UUID(payload["candidate"]["id"])
            )
        )
        events = list(
            session.scalars(
                select(EventLog)
                .where(
                    EventLog.task_id == UUID(seeded["task_id"]),
                    EventLog.event_type.in_(
                        (
                            "WorkflowJobQueued",
                            "ReleaseCandidateApprovalRequested",
                        )
                    ),
                )
                .order_by(EventLog.created_at, EventLog.id)
            )
        )
        assert candidate is not None
        assert approval is not None
        assert job is not None
        assert job.job_type == "release_candidate_reconcile"
        assert job.status == "pending"
        assert set(job.payload_json) == {
            "schema_version",
            "candidate_id",
            "approval_id",
            "expected_candidate_request_hash",
            "expected_binding_snapshot_sha256",
            "expected_pull_request_record_id",
        }
        assert len(events) == 2
        for event in events:
            assert set(event.payload) == (
                QUEUED_EVENT_FIELDS
                if event.event_type == "WorkflowJobQueued"
                else REQUESTED_EVENT_FIELDS
            )
            serialized = json.dumps(event.payload, sort_keys=True)
            assert "clone_url" not in serialized
            assert "credential_ref" not in serialized
            assert "profile_key" not in serialized
            assert "test-repository-primary-token" not in serialized


@pytest.mark.parametrize(
    ("body_mode", "body"),
    [
        ("json", {"extra": "forbidden"}),
        ("json", None),
        ("json", []),
        ("missing", None),
    ],
)
def test_candidate_post_requires_strict_empty_object(
    client: TestClient,
    body_mode: str,
    body,
) -> None:
    """额外字段、null、数组和缺失 body 均返回稳定 validation_error。"""

    seeded = seed_release_candidate_dependencies(client)
    path = f"/api/tasks/{seeded['task_id']}/release-candidate"
    response = (
        client.post(path, json=body)
        if body_mode == "json"
        else client.post(path)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_candidate_post_requires_binding_open_pr_and_creator(
    client: TestClient,
) -> None:
    """按顺序区分 Binding、open PR 和实现 AgentRun 缺失。"""

    seeded = seed_release_candidate_dependencies(client)
    path = f"/api/tasks/{seeded['task_id']}/release-candidate"
    with Session(get_engine()) as session:
        binding_id = UUID(seeded["repository_binding_id"])
        binding = session.get(ProjectRepositoryBinding, binding_id)
        assert binding is not None
        binding.status = "disabled"
        session.commit()
    inactive = client.post(path, json={})
    assert inactive.status_code == 409
    assert inactive.json()["code"] == "repository_binding_inactive"

    with Session(get_engine()) as session:
        binding = session.get(
            ProjectRepositoryBinding,
            UUID(seeded["repository_binding_id"]),
        )
        pull_request = session.get(
            PullRequestRecord,
            UUID(seeded["pull_request_record_id"]),
        )
        assert binding is not None
        assert pull_request is not None
        binding.status = "active"
        pull_request.created_by_agent_run_id = None
        session.commit()
    missing_creator = client.post(path, json={})
    assert missing_creator.status_code == 409
    assert (
        missing_creator.json()["code"]
        == "m6_pull_request_creator_required"
    )

    with Session(get_engine()) as session:
        pull_request = session.get(
            PullRequestRecord,
            UUID(seeded["pull_request_record_id"]),
        )
        assert pull_request is not None
        pull_request.status = "closed"
        session.commit()
    missing_open_pr = client.post(path, json={})
    assert missing_open_pr.status_code == 409
    assert missing_open_pr.json()["code"] == "m6_pull_request_required"


def test_new_pull_request_stales_old_candidate_and_allows_new_identity(
    client: TestClient,
) -> None:
    """新 PR 原子失效旧 Candidate 后允许创建下一业务身份。"""

    seeded = seed_release_candidate_dependencies(client)
    path = f"/api/tasks/{seeded['task_id']}/release-candidate"
    first = client.post(path, json={})
    assert first.status_code == 201
    create_new_open_pull_request(seeded["task_id"])

    response = client.post(path, json={})

    assert response.status_code == 201, response.text
    assert (
        response.json()["candidate"]["id"]
        != first.json()["candidate"]["id"]
    )
    with Session(get_engine()) as session:
        old_candidate = session.get(
            ReleaseCandidate,
            UUID(first.json()["candidate"]["id"]),
        )
        old_approval = session.get(
            ApprovalRequest,
            UUID(first.json()["approval"]["id"]),
        )
        assert old_candidate is not None
        assert old_approval is not None
        assert old_candidate.status == "stale"
        assert old_approval.status == "expired"


def test_concurrent_identical_candidate_posts_return_201_and_200(
    client: TestClient,
) -> None:
    """Task 行锁使并发相同 POST 只形成一组三表资源。"""

    seeded = seed_release_candidate_dependencies(client)
    path = f"/api/tasks/{seeded['task_id']}/release-candidate"
    barrier = Barrier(2)

    def request_candidate() -> tuple[int, dict]:
        with TestClient(create_app()) as thread_client:
            barrier.wait(timeout=10)
            response = thread_client.post(path, json={})
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: request_candidate(), range(2)))

    assert sorted(status_code for status_code, _payload in results) == [
        200,
        201,
    ]
    assert results[0][1] == results[1][1]
    with Session(get_engine()) as session:
        task_id = UUID(seeded["task_id"])
        assert (
            session.scalar(
                select(func.count(ReleaseCandidate.id)).where(
                    ReleaseCandidate.task_id == task_id
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(WorkflowJob.id)).where(
                    WorkflowJob.task_id == task_id
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(ApprovalRequest.id)).where(
                    ApprovalRequest.task_id == task_id,
                    ApprovalRequest.action
                    == "approve_release_candidate",
                )
            )
            == 1
        )
        for event_type in (
            "WorkflowJobQueued",
            "ReleaseCandidateApprovalRequested",
        ):
            assert (
                session.scalar(
                    select(func.count(EventLog.id)).where(
                        EventLog.task_id == task_id,
                        EventLog.event_type == event_type,
                    )
                )
                == 1
            )


def test_candidate_openapi_contract_is_exact() -> None:
    """strict empty、200/201 envelope 和 public DTO 均进入 OpenAPI。"""

    schema = app.openapi()
    operation = schema["paths"][
        "/api/tasks/{task_id}/release-candidate"
    ]["post"]
    create_schema = schema["components"]["schemas"][
        "ReleaseCandidateCreate"
    ]
    assert operation["requestBody"]["required"] is True
    assert create_schema["properties"] == {}
    assert create_schema["additionalProperties"] is False
    for status_code in ("200", "201"):
        assert operation["responses"][status_code]["content"][
            "application/json"
        ]["schema"] == {
            "$ref": "#/components/schemas/ReleaseCandidateEnvelope"
        }
    for model_name in (
        "ReleaseCandidateEnvelope",
        "ReleaseCandidateRead",
        "ReleaseCandidateApprovalRead",
        "RepositoryBindingSnapshotRead",
    ):
        assert (
            schema["components"]["schemas"][model_name][
                "additionalProperties"
            ]
            is False
        )
    assert schema["components"]["schemas"][
        "ReleaseCandidateApprovalRead"
    ]["properties"]["risk_level"]["const"] == "L2"
    assert all(
        "workflow-job" not in path
        for path in schema["paths"]
    )


def test_candidate_get_prefers_active_then_latest_history(
    client: TestClient,
) -> None:
    """active Candidate 优先于较新的历史；无 active 时按创建时间返回。"""

    seeded = seed_release_candidate_dependencies(client)
    path = f"/api/tasks/{seeded['task_id']}/release-candidate"
    first = client.post(path, json={})
    assert first.status_code == 201
    rejected_first = client.post(
        f"/api/approvals/{first.json()['approval']['id']}/reject",
        json={"actor_id": "reviewer-1"},
    )
    assert rejected_first.status_code == 200
    create_new_open_pull_request(seeded["task_id"])
    second = client.post(path, json={})
    assert second.status_code == 201

    with Session(get_engine()) as session:
        first_candidate = session.get(
            ReleaseCandidate,
            UUID(first.json()["candidate"]["id"]),
        )
        database_now = session.scalar(select(func.now()))
        assert first_candidate is not None
        assert database_now is not None
        first_candidate.created_at = database_now.replace(
            year=database_now.year + 1
        )
        first_candidate.updated_at = first_candidate.created_at
        session.commit()

    active_get = client.get(path)
    assert active_get.status_code == 200
    assert (
        active_get.json()["candidate"]["id"]
        == second.json()["candidate"]["id"]
    )

    rejected_second = client.post(
        f"/api/approvals/{second.json()['approval']['id']}/reject",
        json={"actor_id": "reviewer-2"},
    )
    assert rejected_second.status_code == 200
    historical_get = client.get(path)
    assert historical_get.status_code == 200
    assert (
        historical_get.json()["candidate"]["id"]
        == first.json()["candidate"]["id"]
    )
