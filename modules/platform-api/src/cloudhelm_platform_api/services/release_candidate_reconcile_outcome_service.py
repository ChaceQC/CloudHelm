"""ReleaseCandidate reconcile 的状态组合、freshness 与成功结果收敛。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.pull_request_record_repository import (
    PullRequestRecordRepository,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    ReleaseCandidateReconcilePayload,
    ReleaseCandidateReconcileResult,
)
from cloudhelm_platform_api.services.release_candidate_approval_policy import (
    ReleaseCandidateApprovalPolicy,
)
from cloudhelm_platform_api.services.release_candidate_freshness import (
    ReleaseCandidateFreshnessService,
)
from cloudhelm_platform_api.services.release_candidate_reconcile_support import (
    ACTIVE_PAIRS,
    STALE_DECISION_PAIRS,
    TERMINAL_NOOP_PAIRS,
    reconcile_expected_candidate_is_fresh,
)
from cloudhelm_platform_api.services.workflow_job_terminal_service import (
    WorkflowJobTerminalService,
)


class ReleaseCandidateReconcileOutcomeService:
    """在调用方已持有全部资源锁后收敛 Candidate/Approval/job。"""

    def __init__(self, session: Session) -> None:
        self.pull_requests = PullRequestRecordRepository(session)
        self.policy = ReleaseCandidateApprovalPolicy(session)
        self.freshness = ReleaseCandidateFreshnessService(session)
        self.terminal = WorkflowJobTerminalService(session)

    def reconcile(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        binding: ProjectRepositoryBinding,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        payload: ReleaseCandidateReconcilePayload,
        checked_at: datetime,
    ) -> WorkflowJob:
        """按状态组合优先级处理 terminal、stale、invalid 与 active。"""

        pair = (candidate.status, approval.status)
        if pair in TERMINAL_NOOP_PAIRS:
            return self._succeed(
                job,
                candidate=candidate,
                approval=approval,
                checked_at=checked_at,
                outcome="terminal_noop",
            )
        if pair in STALE_DECISION_PAIRS:
            return self._stale(
                job,
                candidate=candidate,
                approval=approval,
                checked_at=checked_at,
                reason="release_candidate_approval_no_longer_active",
            )
        if pair not in ACTIVE_PAIRS:
            return self.terminal.fail(
                job,
                database_now=checked_at,
                error_code="release_candidate_approval_state_invalid",
            )
        return self._reconcile_active(
            task=task,
            job=job,
            binding=binding,
            candidate=candidate,
            approval=approval,
            payload=payload,
            checked_at=checked_at,
        )

    def _reconcile_active(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        binding: ProjectRepositoryBinding,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        payload: ReleaseCandidateReconcilePayload,
        checked_at: datetime,
    ) -> WorkflowJob:
        """依次核验冻结 identity、Approval 契约和当前外部事实。"""

        if not reconcile_expected_candidate_is_fresh(
            payload=payload,
            candidate=candidate,
        ):
            return self._stale(
                job,
                candidate=candidate,
                approval=approval,
                checked_at=checked_at,
                reason="release_candidate_expected_identity_drift",
            )
        if not self.policy.reconcile_approval_contract_is_fresh(
            candidate=candidate,
            approval=approval,
        ):
            return self._stale(
                job,
                candidate=candidate,
                approval=approval,
                checked_at=checked_at,
                reason="release_candidate_approval_contract_drift",
            )
        return self._reconcile_current_facts(
            task=task,
            job=job,
            binding=binding,
            candidate=candidate,
            approval=approval,
            checked_at=checked_at,
        )

    def _reconcile_current_facts(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        binding: ProjectRepositoryBinding,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        checked_at: datetime,
    ) -> WorkflowJob:
        """复核最新版 PR、审批有效期和 Binding canonical。"""

        pull_request = self.pull_requests.latest_open_by_task(task.id)
        fresh = (
            binding.status == "active"
            and approval.expires_at is not None
            and approval.expires_at > checked_at
            and approval.consumed_at is None
            and self.policy.is_fresh(
                task=task,
                binding=binding,
                candidate=candidate,
                approval=approval,
                pull_request=pull_request,
            )
        )
        if not fresh:
            return self._stale(
                job,
                candidate=candidate,
                approval=approval,
                checked_at=checked_at,
                reason="release_candidate_reconcile_freshness_drift",
            )
        return self._succeed(
            job,
            candidate=candidate,
            approval=approval,
            checked_at=checked_at,
            outcome="valid",
        )

    def _stale(
        self,
        job: WorkflowJob,
        *,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        checked_at: datetime,
        reason: str,
    ) -> WorkflowJob:
        """原子 stale Candidate、按需 expire pending Approval 并成功收敛。"""

        self.freshness.invalidate_locked(
            candidate,
            approval,
            now=checked_at,
            reason=reason,
        )
        return self._succeed(
            job,
            candidate=candidate,
            approval=approval,
            checked_at=checked_at,
            outcome="stale",
        )

    def _succeed(
        self,
        job: WorkflowJob,
        *,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        checked_at: datetime,
        outcome: str,
    ) -> WorkflowJob:
        """构造严格 result，再交由统一终态服务写入。"""

        result = ReleaseCandidateReconcileResult(
            outcome=outcome,
            candidate_status=candidate.status,
            approval_status=approval.status,
            pull_request_record_id=candidate.pull_request_record_id,
            binding_snapshot_sha256=candidate.binding_snapshot_sha256,
            checked_at=checked_at,
        )
        return self.terminal.succeed(
            job,
            database_now=checked_at,
            result_json=result.model_dump(mode="json"),
            outcome=outcome,
        )
