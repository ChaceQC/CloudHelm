"""M7-2B2 ReleaseCandidate API 测试依赖构造器。"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordCreate,
)
from cloudhelm_platform_api.services.pull_request_record_service import (
    PullRequestRecordService,
)
from m6_evidence_fixture import seed_m6_evidence


def seed_release_candidate_dependencies(
    client: TestClient,
    *,
    label: str | None = None,
    profile_key: str = "test-primary",
) -> dict[str, str]:
    """准备 active Binding、最新 open PR 与真实 creator AgentRun。"""

    suffix = label or uuid4().hex[:10]
    evidence = seed_m6_evidence(
        f"candidate-{suffix}",
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
            summary="M7 Candidate fixture creator",
            started_at=now,
            finished_at=now,
        )
        session.add(creator)
        session.flush()
        pull_request.created_by_agent_run_id = creator.id
        session.commit()
        references = {
            "task_id": str(task.id),
            "project_id": str(task.project_id),
            "pull_request_record_id": str(pull_request.id),
            "creator_agent_run_id": str(creator.id),
        }

    response = client.put(
        f"/api/projects/{references['project_id']}/repository-binding",
        json={"profile_key": profile_key},
    )
    assert response.status_code == 200, response.text
    references["repository_binding_id"] = response.json()["id"]
    return references


def create_new_open_pull_request(task_id: str) -> str:
    """基于同一证据集创建新 commit，并让旧 open PR superseded。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        task_uuid = UUID(task_id)
        previous = PullRequestRecordService(session).records.latest_by_task(
            task_uuid
        )
        assert previous is not None
        record = PullRequestRecordService(session).create(
            PullRequestRecordCreate(
                task_id=previous.task_id,
                project_id=previous.project_id,
                development_plan_id=previous.development_plan_id,
                created_by_agent_run_id=previous.created_by_agent_run_id,
                provider=previous.provider,
                title=f"{previous.title} follow-up",
                summary=previous.summary,
                base_branch=previous.base_branch,
                head_branch=f"{previous.head_branch}-follow-up",
                base_commit_sha=previous.commit_sha,
                commit_sha=f"{uuid4().int:040x}"[-40:],
                changed_files_json=previous.changed_files_json,
                diff_stat_json=previous.diff_stat_json,
                diff_artifact_id=previous.diff_artifact_id,
                test_artifact_id=previous.test_artifact_id,
                review_artifact_id=previous.review_artifact_id,
                security_artifact_id=previous.security_artifact_id,
                idempotency_key=f"follow-up:{uuid4()}",
            )
        )
        session.commit()
        return str(record.id)
