"""M7 `release_candidate_reconcile` 纯数据库 handler。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.approval_repository import (
    ApprovalRepository,
)
from cloudhelm_platform_api.repositories.project_repository_binding_repository import (
    ProjectRepositoryBindingRepository,
)
from cloudhelm_platform_api.repositories.release_candidate_repository import (
    ReleaseCandidateRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    ReleaseCandidateReconcilePayload,
)
from cloudhelm_platform_api.services.release_candidate_approval_policy import (
    ReleaseCandidateApprovalPolicy,
)
from cloudhelm_platform_api.services.release_candidate_reconcile_outcome_service import (
    ReleaseCandidateReconcileOutcomeService,
)
from cloudhelm_platform_api.services.release_candidate_reconcile_support import (
    TERMINAL_TASK_STATUSES,
    owns_live_handler,
    parse_reconcile_payload,
    reconcile_checked_at,
    reconcile_job_identity_is_valid,
)
from cloudhelm_platform_api.services.workflow_job_terminal_service import (
    WorkflowJobTerminalService,
)


class ReleaseCandidateReconcileService:
    """按 Task→Job→Binding→Candidate→Approval 锁序收敛候选发布状态。"""

    def __init__(self, session: Session) -> None:
        self.tasks = TaskRepository(session)
        self.jobs = WorkflowJobRepository(session)
        self.bindings = ProjectRepositoryBindingRepository(session)
        self.candidates = ReleaseCandidateRepository(session)
        self.approvals = ApprovalRepository(session)
        self.policy = ReleaseCandidateApprovalPolicy(session)
        self.terminal = WorkflowJobTerminalService(session)
        self.outcomes = ReleaseCandidateReconcileOutcomeService(session)

    def execute(
        self,
        *,
        workflow_job_id: UUID,
        worker_owner: str,
    ) -> WorkflowJob | None:
        """执行一次当前 owner 的 reconcile；竞争失败保持 no-op。"""

        job_hint = self.jobs.get(workflow_job_id)
        if job_hint is None:
            return None
        payload = parse_reconcile_payload(job_hint)
        candidate_hint = (
            self.candidates.get(payload.candidate_id)
            if payload is not None
            else None
        )

        task = self.tasks.get(job_hint.task_id, for_update=True)
        job = self.jobs.get(workflow_job_id, for_update=True)
        if task is None or job is None or job.task_id != job_hint.task_id:
            return None
        if payload is None:
            database_now = self.jobs.database_now()
            if not owns_live_handler(job, worker_owner, database_now):
                return None
            return self.terminal.fail(
                job,
                database_now=database_now,
                error_code="workflow_job_payload_invalid",
            )
        if candidate_hint is None:
            database_now = self.jobs.database_now()
            if not owns_live_handler(job, worker_owner, database_now):
                return None
            return self.terminal.fail(
                job,
                database_now=database_now,
                error_code="release_candidate_resource_not_found",
            )
        return self._reconcile_locked(
            task=task,
            job=job,
            payload=payload,
            binding_id_hint=candidate_hint.repository_binding_id,
            worker_owner=worker_owner,
        )

    def _reconcile_locked(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        payload: ReleaseCandidateReconcilePayload,
        binding_id_hint: UUID,
        worker_owner: str,
    ) -> WorkflowJob | None:
        """按冻结顺序锁资源，并在全部锁后重验 owner、lease 与时间。"""

        binding = self.bindings.get(binding_id_hint, for_update=True)
        candidate = self.candidates.get(
            payload.candidate_id,
            for_update=True,
        )
        approval = self.approvals.get(
            payload.approval_id,
            for_update=True,
        )
        # Binding/Candidate/Approval 行锁可能发生长等待；最终判断必须使用等待
        # 结束后的数据库时钟，否则过期 lease 或 Approval 会被旧时间误判为有效。
        database_now = self.jobs.database_now()
        if not owns_live_handler(job, worker_owner, database_now):
            return None
        checked_at = reconcile_checked_at(
            job=job,
            database_now=database_now,
            candidate=candidate,
            approval=approval,
            binding=binding,
        )
        return self._apply_locked_reconcile(
            task=task,
            job=job,
            payload=payload,
            binding_id_hint=binding_id_hint,
            binding=binding,
            candidate=candidate,
            approval=approval,
            checked_at=checked_at,
        )

    def _apply_locked_reconcile(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        payload: ReleaseCandidateReconcilePayload,
        binding_id_hint: UUID,
        binding: ProjectRepositoryBinding | None,
        candidate: ReleaseCandidate | None,
        approval: ApprovalRequest | None,
        checked_at: datetime,
    ) -> WorkflowJob:
        """在 fresh lease 下处理取消、资源错误或正常 outcome。"""

        if task.status in TERMINAL_TASK_STATUSES or job.status == (
            "cancel_requested"
        ):
            self._close_owned_resources_for_cancel(
                task=task,
                job=job,
                payload=payload,
                binding_id_hint=binding_id_hint,
                binding=binding,
                candidate=candidate,
                approval=approval,
                checked_at=checked_at,
            )
            return self.terminal.cancel(job, database_now=checked_at)
        error_code = self._locked_resource_error(
            task=task,
            job=job,
            payload=payload,
            binding_id_hint=binding_id_hint,
            binding=binding,
            candidate=candidate,
            approval=approval,
        )
        if error_code is not None:
            return self.terminal.fail(
                job,
                database_now=checked_at,
                error_code=error_code,
            )
        assert binding is not None
        assert candidate is not None
        assert approval is not None
        return self.outcomes.reconcile(
            task=task,
            job=job,
            binding=binding,
            candidate=candidate,
            approval=approval,
            payload=payload,
            checked_at=checked_at,
        )

    def _locked_resource_error(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        payload: ReleaseCandidateReconcilePayload,
        binding_id_hint: UUID,
        binding: ProjectRepositoryBinding | None,
        candidate: ReleaseCandidate | None,
        approval: ApprovalRequest | None,
    ) -> str | None:
        """返回锁后不可恢复的资源/identity/ownership 错误码。"""

        if binding is None or candidate is None:
            return "release_candidate_resource_not_found"
        if approval is None:
            return "release_candidate_approval_state_invalid"
        if not reconcile_job_identity_is_valid(
            job=job,
            payload=payload,
            candidate=candidate,
            approval=approval,
            binding_id_hint=binding_id_hint,
        ):
            return "release_candidate_job_identity_invalid"
        if not self.policy.reconcile_static_ownership_is_valid(
            task=task,
            binding=binding,
            candidate=candidate,
            approval=approval,
        ):
            return "release_candidate_approval_state_invalid"
        return None

    def _close_owned_resources_for_cancel(
        self,
        *,
        task: Task,
        job: WorkflowJob,
        payload: ReleaseCandidateReconcilePayload,
        binding_id_hint: UUID,
        binding: ProjectRepositoryBinding | None,
        candidate: ReleaseCandidate | None,
        approval: ApprovalRequest | None,
        checked_at: datetime,
    ) -> None:
        """只在完整 identity/ownership 通过时关闭关联资源。"""

        if binding is None or candidate is None or approval is None:
            return
        identity_valid = reconcile_job_identity_is_valid(
            job=job,
            payload=payload,
            candidate=candidate,
            approval=approval,
            binding_id_hint=binding_id_hint,
        )
        if (
            not identity_valid
            or not self.policy.reconcile_static_ownership_is_valid(
                task=task,
                binding=binding,
                candidate=candidate,
                approval=approval,
            )
        ):
            return
        # Task cancel 仍关闭与 Candidate 静态绑定的 pending Approval，即使
        # action/resource/hash 已发生 freshness 漂移。
        if candidate.status in {"pending_approval", "approved"}:
            candidate.status = "cancelled"
            candidate.updated_at = checked_at
        if approval.status == "pending":
            approval.status = "expired"
            approval.decided_by = "system:workflow-engine"
            approval.decided_at = checked_at
