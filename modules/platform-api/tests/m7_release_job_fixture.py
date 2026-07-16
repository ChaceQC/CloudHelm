"""M7-2 RepositoryBinding、Candidate、Approval 与 WorkflowJob 测试夹具。"""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.workflow_job import WorkflowJob

from m6_evidence_fixture import seed_m6_evidence


def seed_m7_candidate_dependencies(
    *,
    pull_request_count: int = 2,
) -> dict[str, Any]:
    """准备真实 M1-M6 父记录和一个资源审批，供 M7 数据约束测试复用。

    夹具把 M6 PR creator 绑定到真实 Coder AgentRun，既支撑当前数据库约束测试，
    也可供后续 M7-2B 的来源追溯与自批门禁测试使用。
    """

    suffix = uuid4().hex[:12]
    evidence = seed_m6_evidence(
        f"m7-db-{suffix}",
        pull_request_count=pull_request_count,
    )
    candidate_id = uuid4()
    now = utc_now()
    with Session(get_engine(), expire_on_commit=False) as session:
        task = session.get(Task, evidence.task_id)
        assert task is not None
        creator = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="succeeded",
            summary="M7 migration constraint fixture",
            started_at=now,
            finished_at=now,
        )
        binding = ProjectRepositoryBinding(
            project_id=task.project_id,
            provider="gitea",
            profile_key=f"m7-test-{suffix}",
            repository_external_id=f"repo-{suffix}",
            repository_owner=f"owner-{suffix}",
            repository_name=f"sample-{suffix}",
            clone_url=(
                f"https://gitea.example.test/owner-{suffix}/"
                f"sample-{suffix}.git"
            ),
            default_branch="main",
            credential_ref=f"credential:m7-test:{suffix}",
            workflow_id=".gitea/workflows/cloudhelm-release.yml",
            release_ref_prefix="refs/heads/cloudhelm/release-candidates",
            status="active",
        )
        session.add_all([creator, binding])
        session.flush()
        for pull_request_record_id in evidence.pull_request_record_ids:
            pull_request_record = session.get(
                PullRequestRecord,
                pull_request_record_id,
            )
            assert pull_request_record is not None
            pull_request_record.created_by_agent_run_id = creator.id

        approval = build_release_candidate_approval(
            task_id=task.id,
            requested_by_agent_run_id=creator.id,
            candidate_id=candidate_id,
            request_hash="sha256:" + ("a" * 64),
            now=now,
        )
        session.add(approval)
        session.commit()
        return {
            "candidate_id": candidate_id,
            "task_id": task.id,
            "project_id": task.project_id,
            "pull_request_record_id": evidence.pull_request_record_ids[-1],
            "pull_request_record_ids": evidence.pull_request_record_ids,
            "repository_binding_id": binding.id,
            "approval_id": approval.id,
            "creator_agent_run_id": creator.id,
        }


def build_release_candidate_approval(
    *,
    task_id: UUID,
    requested_by_agent_run_id: UUID,
    candidate_id: UUID | None = None,
    request_hash: str | None = None,
    now: Any | None = None,
    **overrides: Any,
) -> ApprovalRequest:
    """构造默认合法的 ReleaseCandidate L2 资源审批。"""

    current_time = now or utc_now()
    resource_id = candidate_id or uuid4()
    values: dict[str, Any] = {
        "task_id": task_id,
        "action": "approve_release_candidate",
        "risk_level": "L2",
        "reason": "验证 M7 Candidate 数据约束。",
        "resource_type": "release_candidate",
        "resource_id": resource_id,
        "request_hash": request_hash or "sha256:" + ("a" * 64),
        "status": "pending",
        "requested_by_agent_run_id": requested_by_agent_run_id,
        "expires_at": current_time + timedelta(minutes=30),
        "created_at": current_time,
    }
    values.update(overrides)
    return ApprovalRequest(**values)


def valid_binding_snapshot() -> dict[str, Any]:
    """返回 M7 文档冻结的八字段公开仓库快照。"""

    return {
        "schema_version": "m7.repository-binding.snapshot.v1",
        "provider": "gitea",
        "repository_external_id": "repo-migration-test",
        "repository_owner": "cloudhelm",
        "repository_name": "sample-service",
        "default_branch": "main",
        "workflow_id": ".gitea/workflows/cloudhelm-release.yml",
        "release_ref_prefix": "refs/heads/cloudhelm/release-candidates",
    }


def build_release_candidate(
    references: dict[str, Any],
    **overrides: Any,
) -> ReleaseCandidate:
    """构造默认合法的 Candidate，允许测试只覆盖一个约束字段。"""

    candidate_id = overrides.pop("id", references["candidate_id"])
    values: dict[str, Any] = {
        "id": candidate_id,
        "task_id": references["task_id"],
        "project_id": references["project_id"],
        "pull_request_record_id": references["pull_request_record_id"],
        "repository_binding_id": references["repository_binding_id"],
        "binding_snapshot_json": valid_binding_snapshot(),
        "binding_snapshot_sha256": "sha256:" + ("b" * 64),
        "commit_sha": "1" * 40,
        "target_ref": (
            "refs/heads/cloudhelm/release-candidates/"
            f"{candidate_id.hex}"
        ),
        "request_hash": "sha256:" + ("c" * 64),
        "approval_id": references["approval_id"],
        "status": "pending_approval",
        "idempotency_key": f"candidate:{candidate_id}",
    }
    values.update(overrides)
    return ReleaseCandidate(**values)


def build_workflow_job(
    references: dict[str, Any],
    **overrides: Any,
) -> WorkflowJob:
    """构造默认合法的 pending reconcile job。"""

    resource_id = overrides.pop("resource_id", references["candidate_id"])
    values: dict[str, Any] = {
        "task_id": references["task_id"],
        "job_type": "release_candidate_reconcile",
        "resource_type": "release_candidate",
        "resource_id": resource_id,
        "side_effect_class": "none",
        "request_hash": "sha256:" + ("d" * 64),
        "idempotency_key": f"reconcile:{resource_id}",
        "status": "pending",
        "attempt": 0,
        "max_attempts": 3,
        "enqueue_attempt": 0,
        "payload_json": {},
    }
    values.update(overrides)
    return WorkflowJob(**values)
