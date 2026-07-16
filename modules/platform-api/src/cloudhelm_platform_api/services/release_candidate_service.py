"""M7 ReleaseCandidate、第一道审批与 reconcile job 原子服务。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.approval_repository import (
    ApprovalRepository,
)
from cloudhelm_platform_api.repositories.project_repository_binding_repository import (
    ProjectRepositoryBindingRepository,
)
from cloudhelm_platform_api.repositories.pull_request_record_repository import (
    PullRequestRecordRepository,
)
from cloudhelm_platform_api.repositories.release_candidate_repository import (
    ReleaseCandidateRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.schemas.release_candidate import (
    ReleaseCandidateEnvelope,
    release_candidate_approval_to_read,
    release_candidate_to_read,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.pull_request_record_gate import (
    PullRequestRecordGate,
)
from cloudhelm_platform_api.services.release_candidate_policy import (
    APPROVAL_ACTION,
    RECONCILE_JOB_TYPE,
    ReleaseCandidateIdentity,
    build_reconcile_job_spec,
    build_release_candidate_identity,
)
from cloudhelm_platform_api.services.release_candidate_records import (
    ReleaseCandidateRecordFactory,
)

_TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}


@dataclass(frozen=True)
class ReleaseCandidateCreateResult:
    """区分首次创建与幂等命中的内部结果。"""

    envelope: ReleaseCandidateEnvelope
    created: bool


class ReleaseCandidateService(BaseService):
    """在单一 PostgreSQL 事务创建 Candidate、Approval、Job 与事件。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.bindings = ProjectRepositoryBindingRepository(session)
        self.pull_requests = PullRequestRecordRepository(session)
        self.candidates = ReleaseCandidateRepository(session)
        self.approvals = ApprovalRepository(session)
        self.workflow_jobs = WorkflowJobRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.pull_request_gate = PullRequestRecordGate(session)
        self.record_factory = ReleaseCandidateRecordFactory(session)

    def create(self, task_id: UUID) -> ReleaseCandidateCreateResult:
        """按 Task→Binding→PR→Candidate 锁序创建或复用候选发布。"""

        task = self.tasks.get(task_id, for_update=True)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        if task.status in _TERMINAL_TASK_STATUSES:
            raise ServiceError(
                "task_terminal",
                "终态任务不能创建候选发布。",
                409,
            )

        binding = self.bindings.get_by_project(
            task.project_id,
            for_update=True,
        )
        if binding is None:
            raise ServiceError(
                "repository_binding_not_found",
                "Project 尚未配置 RepositoryBinding。",
                404,
            )
        if binding.status != "active":
            raise ServiceError(
                "repository_binding_inactive",
                "RepositoryBinding 已禁用。",
                409,
            )

        pull_request = self.pull_requests.latest_open_by_task_for_update(
            task.id
        )
        if pull_request is None:
            raise ServiceError(
                "m6_pull_request_required",
                "缺少符合门禁的最新 open PullRequestRecord。",
                409,
            )
        self._validate_pull_request(task, pull_request)

        identity = build_release_candidate_identity(
            binding=binding,
            task_id=task.id,
            project_id=task.project_id,
            pull_request_record_id=pull_request.id,
            commit_sha=pull_request.commit_sha,
        )
        existing = self.candidates.get_by_pr_snapshot_for_update(
            pull_request.id,
            identity.binding_snapshot_sha256,
        )
        if existing is not None:
            envelope = self._existing_envelope(
                existing,
                identity=identity,
                creator_agent_run_id=(
                    pull_request.created_by_agent_run_id
                ),
            )
            self.session.rollback()
            return ReleaseCandidateCreateResult(
                envelope=envelope,
                created=False,
            )

        if self.candidates.get_active_by_task_for_update(task.id) is not None:
            raise ServiceError(
                "release_candidate_conflict",
                "同一 Task 已存在不同业务身份的可推进 Candidate。",
                409,
            )

        database_now = self.approvals.database_now()
        records = self.record_factory.create(
            task=task,
            binding=binding,
            pull_request=pull_request,
            identity=identity,
            database_now=database_now,
        )
        self.commit()
        return ReleaseCandidateCreateResult(
            envelope=self._envelope(
                records.candidate,
                records.approval,
            ),
            created=True,
        )

    def get(self, task_id: UUID) -> ReleaseCandidateEnvelope:
        """返回 active-first Candidate；没有 active 时返回最新历史。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        candidate = self.candidates.latest_by_task(task_id)
        if candidate is None:
            raise ServiceError(
                "release_candidate_not_found",
                "Task 尚无 ReleaseCandidate。",
                404,
            )
        approval = self.approvals.get(candidate.approval_id)
        if approval is None:
            raise ServiceError(
                "database_error",
                "Candidate 审批引用无效。",
                500,
            )
        return self._envelope(candidate, approval)

    def _validate_pull_request(self, task, pull_request) -> None:
        """复核最新 open PR 的归属、门禁与实现者 provenance。"""

        if pull_request.project_id != task.project_id:
            raise ServiceError(
                "m6_pull_request_required",
                "最新 open PullRequestRecord 不属于当前 Project。",
                409,
            )
        try:
            self.pull_request_gate.validate_record(pull_request)
        except ServiceError as exc:
            raise ServiceError(
                "m6_pull_request_required",
                "最新 open PullRequestRecord 已不满足 M6 门禁。",
                409,
            ) from exc
        creator_id = pull_request.created_by_agent_run_id
        creator = (
            self.agent_runs.get(creator_id)
            if creator_id is not None
            else None
        )
        if creator is None or creator.task_id != task.id:
            raise ServiceError(
                "m6_pull_request_creator_required",
                "PullRequestRecord 缺少可审计的实现 AgentRun。",
                409,
            )

    def _existing_envelope(
        self,
        candidate: ReleaseCandidate,
        *,
        identity: ReleaseCandidateIdentity,
        creator_agent_run_id: UUID | None,
    ) -> ReleaseCandidateEnvelope:
        """验证幂等记录的三表不可变身份后返回原 envelope。"""

        approval = self.approvals.get(
            candidate.approval_id,
            for_update=True,
        )
        job = self.workflow_jobs.get_by_resource(
            job_type=RECONCILE_JOB_TYPE,
            resource_type="release_candidate",
            resource_id=candidate.id,
            for_update=True,
        )
        if approval is None or job is None or creator_agent_run_id is None:
            raise ServiceError(
                "release_candidate_conflict",
                "Candidate 原子资源引用不完整。",
                409,
            )
        job_spec = build_reconcile_job_spec(
            candidate_id=candidate.id,
            approval_id=approval.id,
            pull_request_record_id=candidate.pull_request_record_id,
            candidate_request_hash=identity.request_hash,
            binding_snapshot_sha256=identity.binding_snapshot_sha256,
        )
        valid = (
            candidate.binding_snapshot_json == identity.public_snapshot
            and candidate.target_ref == identity.target_ref
            and candidate.request_hash == identity.request_hash
            and candidate.idempotency_key == identity.idempotency_key
            and approval.task_id == candidate.task_id
            and approval.action == APPROVAL_ACTION
            and approval.risk_level == "L2"
            and approval.resource_type == "release_candidate"
            and approval.resource_id == candidate.id
            and approval.request_hash == identity.request_hash
            and approval.requested_by_agent_run_id
            == creator_agent_run_id
            and job.task_id == candidate.task_id
            and job.request_hash == job_spec.request_hash
            and job.idempotency_key == job_spec.idempotency_key
            and job.payload_json == job_spec.payload
        )
        if not valid:
            raise ServiceError(
                "release_candidate_conflict",
                "同一 Candidate 业务身份对应的原子资源已漂移。",
                409,
            )
        return self._envelope(candidate, approval)

    @staticmethod
    def _envelope(
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
    ) -> ReleaseCandidateEnvelope:
        """构造稳定 public envelope。"""

        return ReleaseCandidateEnvelope(
            candidate=release_candidate_to_read(candidate),
            approval=release_candidate_approval_to_read(approval),
        )
