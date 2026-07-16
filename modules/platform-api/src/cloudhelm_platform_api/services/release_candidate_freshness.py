"""ReleaseCandidate freshness 失效与 Approval 过期的共享事务逻辑。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.repositories.approval_repository import (
    ApprovalRepository,
)
from cloudhelm_platform_api.repositories.release_candidate_repository import (
    ReleaseCandidateRepository,
)
from cloudhelm_platform_api.services.event_service import EventService

FRESHNESS_ACTOR = "system:release_candidate_freshness"


class ReleaseCandidateFreshnessService:
    """复用 Candidate stale、pending Approval expired 和事件写入。"""

    def __init__(self, session: Session) -> None:
        self.candidates = ReleaseCandidateRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)

    def invalidate_active_by_task(
        self,
        task_id: UUID,
        *,
        current_pull_request_record_id: UUID,
        reason: str,
    ) -> tuple[list[str], list[str]]:
        """新 PR 出现时锁定并失效仍引用旧 PR 的 active Candidate。"""

        candidate = self.candidates.get_active_by_task_for_update(task_id)
        if (
            candidate is None
            or candidate.pull_request_record_id
            == current_pull_request_record_id
        ):
            return [], []
        approval = self.approvals.get(
            candidate.approval_id,
            for_update=True,
        )
        now = self.approvals.database_now()
        return self.invalidate_locked(
            candidate,
            approval,
            now=now,
            reason=reason,
        )

    def invalidate_by_binding(
        self,
        repository_binding_id: UUID,
        *,
        reason: str,
    ) -> tuple[list[str], list[str]]:
        """按 UUID 顺序失效 Binding 下全部 pending/approved Candidate。"""

        candidates = self.candidates.list_active_by_binding_for_update(
            repository_binding_id
        )
        approvals = self.approvals.list_by_ids_for_update(
            sorted(candidate.approval_id for candidate in candidates)
        )
        approvals_by_id = {approval.id: approval for approval in approvals}
        now = self.approvals.database_now()
        stale_ids: list[str] = []
        expired_ids: list[str] = []
        for candidate in candidates:
            stale, expired = self.invalidate_locked(
                candidate,
                approvals_by_id.get(candidate.approval_id),
                now=now,
                reason=reason,
            )
            stale_ids.extend(stale)
            expired_ids.extend(expired)
        return stale_ids, expired_ids

    def invalidate_locked(
        self,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest | None,
        *,
        now: datetime,
        reason: str,
    ) -> tuple[list[str], list[str]]:
        """更新已锁 Candidate/Approval；调用方负责最终提交。"""

        effective_now = max(
            now,
            candidate.created_at,
            approval.created_at if approval is not None else candidate.created_at,
        )
        candidate.status = "stale"
        candidate.updated_at = effective_now
        stale_ids = [str(candidate.id)]
        expired_ids: list[str] = []
        if approval is not None and approval.status == "pending":
            approval.status = "expired"
            approval.decided_by = FRESHNESS_ACTOR
            approval.decided_at = effective_now
            expired_ids.append(str(approval.id))
            self.events.record(
                "ApprovalExpired",
                "system",
                FRESHNESS_ACTOR,
                {
                    "approval_id": str(approval.id),
                    "action": approval.action,
                    "resource_type": approval.resource_type,
                    "resource_id": str(approval.resource_id),
                    "reason": reason,
                    "repository_binding_id": str(
                        candidate.repository_binding_id
                    ),
                },
                candidate.task_id,
            )
        return stale_ids, expired_ids
