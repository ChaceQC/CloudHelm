"""ReleaseCandidate 审批的锁后归属、canonical 与事件策略。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.pull_request_record_gate import (
    PullRequestRecordGate,
)
from cloudhelm_platform_api.services.release_candidate_policy import (
    APPROVAL_ACTION,
    build_release_candidate_identity,
)
from cloudhelm_platform_api.services.repository_binding_snapshot import (
    internal_snapshot_hash_from_binding,
    public_snapshot_from_binding,
)


class ReleaseCandidateApprovalPolicy:
    """在持锁资源上重建当前 identity，避免信任两条共同漂移的 hash。"""

    def __init__(self, session: Session) -> None:
        self.pull_request_gate = PullRequestRecordGate(session)

    @staticmethod
    def locked_ownership_is_valid(
        *,
        task,
        binding,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
    ) -> bool:
        """校验 Task/Project/Binding/Candidate/Approval 的静态归属。"""

        return (
            candidate.task_id == task.id
            and candidate.project_id == task.project_id
            and binding.id == candidate.repository_binding_id
            and binding.project_id == task.project_id
            and candidate.approval_id == approval.id
            and approval.task_id == task.id
            and approval.action == APPROVAL_ACTION
            and approval.risk_level == "L2"
            and approval.resource_type == "release_candidate"
            and approval.resource_id == candidate.id
            and approval.requested_by_agent_run_id is not None
        )

    def is_fresh(
        self,
        *,
        task,
        binding,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        pull_request,
    ) -> bool:
        """复核最新版 open PR、M6 证据和当前 Binding canonical。"""

        if (
            pull_request is None
            or pull_request.id != candidate.pull_request_record_id
            or pull_request.task_id != task.id
            or pull_request.project_id != task.project_id
            or pull_request.created_by_agent_run_id
            != approval.requested_by_agent_run_id
            or pull_request.commit_sha != candidate.commit_sha
        ):
            return False
        try:
            self.pull_request_gate.validate_record(pull_request)
            identity = build_release_candidate_identity(
                binding=binding,
                task_id=task.id,
                project_id=task.project_id,
                pull_request_record_id=pull_request.id,
                commit_sha=pull_request.commit_sha,
            )
        except (ServiceError, ValueError):
            return False
        return (
            candidate.binding_snapshot_json
            == public_snapshot_from_binding(binding)
            and candidate.binding_snapshot_sha256
            == internal_snapshot_hash_from_binding(binding)
            and candidate.binding_snapshot_sha256
            == identity.binding_snapshot_sha256
            and candidate.target_ref == identity.target_ref
            and candidate.request_hash == identity.request_hash
            and candidate.idempotency_key == identity.idempotency_key
        )

    @staticmethod
    def decision_event_payload(
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        *,
        reason: str | None,
    ) -> dict[str, str | None]:
        """构造 Candidate 决策事件的精确低敏资源字段。"""

        return {
            "candidate_id": str(candidate.id),
            "approval_id": str(approval.id),
            "pull_request_record_id": str(
                candidate.pull_request_record_id
            ),
            "repository_binding_id": str(
                candidate.repository_binding_id
            ),
            "binding_snapshot_sha256": (
                candidate.binding_snapshot_sha256
            ),
            "candidate_request_hash": candidate.request_hash,
            "status": candidate.status,
            "reason": reason,
        }
