"""M7 RepositoryBinding API、漂移和并发测试共享夹具。"""

from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.services.repository_binding_snapshot import (
    internal_snapshot_hash_from_binding,
    public_snapshot_from_binding,
)
from m6_evidence_fixture import seed_m6_evidence

REPOSITORY_BINDING_EVENT_FIELDS = {
    "project_id",
    "repository_binding_id",
    "profile_key",
    "provider",
    "repository_external_id",
    "repository_owner",
    "repository_name",
    "default_branch",
    "workflow_id",
    "release_ref_prefix",
    "status",
    "created",
    "configuration_changed",
    "stale_candidate_ids",
    "expired_approval_ids",
}
APPROVAL_EXPIRED_EVENT_FIELDS = {
    "approval_id",
    "action",
    "resource_type",
    "resource_id",
    "reason",
    "repository_binding_id",
}


def event_count(event_type: str) -> int:
    """读取指定事件数量。"""

    with Session(get_engine()) as session:
        return int(
            session.scalar(
                select(func.count(EventLog.id)).where(
                    EventLog.event_type == event_type
                )
            )
            or 0
        )


def seed_candidate(
    client: TestClient,
    *,
    candidate_status: str,
) -> dict[str, str]:
    """准备引用 API Binding 的真实 M6 PR、Candidate 和 Approval。"""

    evidence = seed_m6_evidence(
        f"binding-{candidate_status}-{uuid4().hex[:8]}",
        pull_request_count=1,
    )
    now = utc_now()
    with Session(get_engine(), expire_on_commit=False) as session:
        task = session.get(Task, evidence.task_id)
        pull_request = session.get(
            PullRequestRecord,
            evidence.pull_request_record_ids[-1],
        )
        assert task is not None
        assert pull_request is not None
        creator = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="succeeded",
            summary="RepositoryBinding drift fixture",
            started_at=now,
            finished_at=now,
        )
        session.add(creator)
        session.flush()
        pull_request.created_by_agent_run_id = creator.id
        project_id = task.project_id
        task_id = task.id
        pull_request_id = pull_request.id
        commit_sha = pull_request.commit_sha
        creator_id = creator.id
        session.commit()

    put_response = client.put(
        f"/api/projects/{project_id}/repository-binding",
        json={"profile_key": "test-primary"},
    )
    assert put_response.status_code == 200, put_response.text

    candidate_id = uuid4()
    with Session(get_engine(), expire_on_commit=False) as session:
        binding = session.scalar(
            select(ProjectRepositoryBinding).where(
                ProjectRepositoryBinding.project_id == project_id
            )
        )
        assert binding is not None
        snapshot_hash = internal_snapshot_hash_from_binding(binding)
        snapshot_hex = snapshot_hash.removeprefix("sha256:")
        request_hash = "sha256:" + candidate_id.hex + candidate_id.hex
        approval_status = (
            "approved"
            if candidate_status in {"approved", "published"}
            else "pending"
        )
        approval = ApprovalRequest(
            task_id=task_id,
            action="approve_release_candidate",
            risk_level="L2",
            reason="验证 RepositoryBinding 漂移。",
            resource_type="release_candidate",
            resource_id=candidate_id,
            request_hash=request_hash,
            status=approval_status,
            requested_by_agent_run_id=creator_id,
            decided_by=("reviewer" if approval_status == "approved" else None),
            decided_at=(now if approval_status == "approved" else None),
            expires_at=now + timedelta(hours=1),
            created_at=now,
        )
        session.add(approval)
        session.flush()
        candidate = ReleaseCandidate(
            id=candidate_id,
            task_id=task_id,
            project_id=project_id,
            pull_request_record_id=pull_request_id,
            repository_binding_id=binding.id,
            binding_snapshot_json=public_snapshot_from_binding(binding),
            binding_snapshot_sha256=snapshot_hash,
            commit_sha=commit_sha,
            target_ref=(
                f"{binding.release_ref_prefix}/{task_id}/{commit_sha}/"
                f"{snapshot_hex}"
            ),
            request_hash=request_hash,
            approval_id=approval.id,
            remote_verified_sha=(
                commit_sha if candidate_status == "published" else None
            ),
            status=candidate_status,
            idempotency_key=f"candidate:{candidate_id}",
            approved_at=(
                now
                if candidate_status in {"approved", "published"}
                else None
            ),
            published_at=(now if candidate_status == "published" else None),
            created_at=now,
            updated_at=now,
        )
        session.add(candidate)
        session.commit()
        return {
            "project_id": str(project_id),
            "task_id": str(task_id),
            "candidate_id": str(candidate.id),
            "approval_id": str(approval.id),
        }
