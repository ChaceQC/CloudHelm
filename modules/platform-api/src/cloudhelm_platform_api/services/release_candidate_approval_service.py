"""M7 ReleaseCandidate 第一道审批的专用锁序与 freshness 决策。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
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
from cloudhelm_platform_api.schemas.approval import ApprovalRequestRead
from cloudhelm_platform_api.services.agent_context_messages import (
    append_approval_decision_context,
)
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.release_candidate_approval_policy import (
    ReleaseCandidateApprovalPolicy,
)
from cloudhelm_platform_api.services.release_candidate_freshness import (
    FRESHNESS_ACTOR,
    ReleaseCandidateFreshnessService,
)
from cloudhelm_platform_api.services.release_candidate_policy import (
    normalize_actor_agent_run_id,
)
from cloudhelm_tool_gateway.audit import redact_sensitive_text

_TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}


class ReleaseCandidateApprovalService(BaseService):
    """按 Task→Binding→Candidate→Approval 锁序同步决策两个资源。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.bindings = ProjectRepositoryBindingRepository(session)
        self.candidates = ReleaseCandidateRepository(session)
        self.approvals = ApprovalRepository(session)
        self.pull_requests = PullRequestRecordRepository(session)
        self.policy = ReleaseCandidateApprovalPolicy(session)
        self.freshness = ReleaseCandidateFreshnessService(session)
        self.events = EventService(session)
        self.agent_conversations = AgentConversationService(
            session,
            get_settings(),
        )

    def approve(
        self,
        approval_id: UUID,
        actor_id: str,
        reason: str | None,
    ) -> ApprovalRequestRead:
        """通过第一道审批并把 Candidate 原子转为 approved。"""

        return self._decide(
            approval_id,
            actor_id=actor_id,
            reason=reason,
            approved=True,
        )

    def reject(
        self,
        approval_id: UUID,
        actor_id: str,
        reason: str | None,
    ) -> ApprovalRequestRead:
        """拒绝第一道审批并把 Candidate 原子转为 rejected。"""

        return self._decide(
            approval_id,
            actor_id=actor_id,
            reason=reason,
            approved=False,
        )

    def _decide(
        self,
        approval_id: UUID,
        *,
        actor_id: str,
        reason: str | None,
        approved: bool,
    ) -> ApprovalRequestRead:
        """锁后重验归属、freshness、有效期、自批和 request hash。"""

        approval_hint = self.approvals.get(approval_id)
        if approval_hint is None:
            raise ServiceError(
                "approval_not_found",
                "审批请求不存在。",
                404,
            )
        candidate_hint = self.candidates.get_by_approval_id(approval_id)
        if candidate_hint is None:
            raise ServiceError(
                "release_candidate_stale",
                "审批未绑定有效 ReleaseCandidate。",
                409,
            )

        task = self.tasks.get(approval_hint.task_id, for_update=True)
        if task is None:
            raise ServiceError("task_not_found", "审批关联任务不存在。", 404)
        if task.status in _TERMINAL_TASK_STATUSES:
            raise ServiceError(
                "task_terminal",
                "终态任务不能继续处理审批。",
                409,
            )
        binding = self.bindings.get(
            candidate_hint.repository_binding_id,
            for_update=True,
        )
        candidate = self.candidates.get(
            candidate_hint.id,
            for_update=True,
        )
        approval = self.approvals.get(approval_id, for_update=True)
        if binding is None or candidate is None or approval is None:
            raise ServiceError(
                "release_candidate_stale",
                "Candidate 原子资源引用已失效。",
                409,
            )

        now = max(
            self.approvals.database_now(),
            candidate.created_at,
            approval.created_at,
        )
        if not self.policy.locked_ownership_is_valid(
            task=task,
            binding=binding,
            candidate=candidate,
            approval=approval,
        ):
            self._persist_stale(
                candidate,
                approval,
                now=now,
                reason="approval_resource_mismatch",
            )
            raise ServiceError(
                "approval_request_hash_mismatch",
                "Approval 与 Candidate 资源身份不一致。",
                409,
            )
        if approval.consumed_at is not None:
            raise ServiceError(
                "approval_consumed",
                "资源审批已被单次消费。",
                409,
            )
        if (
            candidate.status == "stale"
            or (
                approval.status == "expired"
                and approval.decided_by == FRESHNESS_ACTOR
            )
        ):
            raise ServiceError(
                "release_candidate_stale",
                "Candidate 的 PR、Binding snapshot 或 request hash 已漂移。",
                409,
            )
        if approval.status != "pending":
            raise ServiceError(
                "invalid_approval_transition",
                "审批请求已决策，不能重复处理。",
                409,
            )
        if approval.expires_at is None or now >= approval.expires_at:
            self._persist_stale(
                candidate,
                approval,
                now=now,
                reason="approval_expired",
            )
            raise ServiceError(
                "approval_expired",
                "资源审批已超过有效期。",
                409,
            )
        if binding.status != "active":
            self._persist_stale(
                candidate,
                approval,
                now=now,
                reason="repository_binding_inactive",
            )
            raise ServiceError(
                "repository_binding_inactive",
                "RepositoryBinding 已禁用。",
                409,
            )
        if candidate.status != "pending_approval":
            raise ServiceError(
                "release_candidate_stale",
                "Candidate 已不处于待审批状态。",
                409,
            )
        if approval.request_hash != candidate.request_hash:
            self._persist_stale(
                candidate,
                approval,
                now=now,
                reason="approval_request_hash_mismatch",
            )
            raise ServiceError(
                "approval_request_hash_mismatch",
                "Approval request hash 与当前 Candidate 不一致。",
                409,
            )

        pull_request = self.pull_requests.latest_open_by_task(task.id)
        if not self.policy.is_fresh(
            task=task,
            binding=binding,
            candidate=candidate,
            approval=approval,
            pull_request=pull_request,
        ):
            self._persist_stale(
                candidate,
                approval,
                now=now,
                reason="release_candidate_stale",
            )
            raise ServiceError(
                "release_candidate_stale",
                "Candidate 的 PR、Binding snapshot 或 request hash 已漂移。",
                409,
            )

        creator_id = approval.requested_by_agent_run_id
        if normalize_actor_agent_run_id(actor_id) == creator_id:
            raise ServiceError(
                "approval_self_decision_forbidden",
                "实现 AgentRun 不得批准自己的候选发布。",
                403,
            )

        normalized_actor = actor_id.strip()
        safe_reason = redact_sensitive_text(reason) if reason else None
        decision = "approved" if approved else "rejected"
        candidate.status = decision
        candidate.approved_at = now if approved else None
        candidate.updated_at = now
        approval.status = decision
        approval.decided_by = normalized_actor
        approval.decided_at = now
        resource_payload = self.policy.decision_event_payload(
            candidate,
            approval,
            reason=safe_reason,
        )
        self.events.record(
            "ReleaseCandidateApproved"
            if approved
            else "ReleaseCandidateRejected",
            "user",
            normalized_actor,
            resource_payload,
            task.id,
        )
        self.events.record(
            "ApprovalApproved" if approved else "ApprovalRejected",
            "user",
            normalized_actor,
            {
                "approval_id": str(approval.id),
                "reason": safe_reason,
                "action": approval.action,
                **resource_payload,
            },
            task.id,
        )
        append_approval_decision_context(
            self.agent_conversations,
            approval,
            status=decision,
            actor_id=normalized_actor,
            reason=safe_reason,
            resource_payload=resource_payload,
        )
        self.commit()
        return ApprovalRequestRead.model_validate(approval)

    def _persist_stale(
        self,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        *,
        now,
        reason: str,
    ) -> None:
        """提交 stale/expired 事实后由调用方返回稳定冲突错误。"""

        self.freshness.invalidate_locked(
            candidate,
            approval,
            now=now,
            reason=reason,
        )
        self.commit()
