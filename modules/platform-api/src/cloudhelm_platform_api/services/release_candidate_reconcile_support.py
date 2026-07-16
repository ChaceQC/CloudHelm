"""ReleaseCandidate reconcile 的纯校验、状态集合与时间辅助函数。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_transition_support import (
    effective_job_time,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    ReleaseCandidateReconcilePayload,
)
from cloudhelm_platform_api.services.release_candidate_policy import (
    RECONCILE_JOB_TYPE,
    build_reconcile_job_spec,
)

TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}
TERMINAL_NOOP_PAIRS = {
    ("rejected", "rejected"),
    ("published", "approved"),
    ("stale", "expired"),
    ("stale", "approved"),
    ("stale", "cancelled"),
    ("cancelled", "expired"),
    ("cancelled", "approved"),
    ("cancelled", "cancelled"),
}
ACTIVE_PAIRS = {
    ("pending_approval", "pending"),
    ("approved", "approved"),
}
STALE_DECISION_PAIRS = {
    ("pending_approval", "expired"),
    ("pending_approval", "cancelled"),
    ("approved", "expired"),
    ("approved", "cancelled"),
}


def parse_reconcile_payload(
    job: WorkflowJob,
) -> ReleaseCandidateReconcilePayload | None:
    """解析严格 payload；非法输入交由持锁 handler 写稳定失败。"""

    try:
        return ReleaseCandidateReconcilePayload.model_validate(job.payload_json)
    except ValidationError:
        return None


def reconcile_job_identity_is_valid(
    *,
    job: WorkflowJob,
    payload: ReleaseCandidateReconcilePayload,
    candidate: ReleaseCandidate,
    approval: ApprovalRequest,
    binding_id_hint: UUID,
) -> bool:
    """使用冻结 payload 重建 canonical job，拒绝 job/payload 共同篡改。"""

    spec = build_reconcile_job_spec(
        candidate_id=payload.candidate_id,
        approval_id=payload.approval_id,
        pull_request_record_id=payload.expected_pull_request_record_id,
        candidate_request_hash=payload.expected_candidate_request_hash,
        binding_snapshot_sha256=(
            payload.expected_binding_snapshot_sha256
        ),
    )
    return (
        job.job_type == RECONCILE_JOB_TYPE
        and job.resource_type == "release_candidate"
        and job.resource_id == candidate.id
        and job.side_effect_class == "none"
        and job.request_hash == spec.request_hash
        and job.idempotency_key == spec.idempotency_key
        and job.payload_json == spec.payload
        and payload.candidate_id == candidate.id
        and payload.approval_id == candidate.approval_id
        and payload.approval_id == approval.id
        and candidate.repository_binding_id == binding_id_hint
    )


def reconcile_expected_candidate_is_fresh(
    *,
    payload: ReleaseCandidateReconcilePayload,
    candidate: ReleaseCandidate,
) -> bool:
    """比较 job 创建时冻结的 Candidate hash/snapshot/PR identity。"""

    return (
        payload.expected_candidate_request_hash
        == candidate.request_hash
        and payload.expected_binding_snapshot_sha256
        == candidate.binding_snapshot_sha256
        and payload.expected_pull_request_record_id
        == candidate.pull_request_record_id
    )


def owns_live_handler(
    job: WorkflowJob,
    worker_owner: str,
    database_now: datetime,
) -> bool:
    """验证 handler 当前 owner、可执行状态和未过期 lease。"""

    return (
        job.status in {"running", "cancel_requested"}
        and job.lease_owner == worker_owner
        and job.lease_expires_at is not None
        and job.lease_expires_at > database_now
    )


def reconcile_checked_at(
    *,
    job: WorkflowJob,
    database_now: datetime,
    candidate: ReleaseCandidate | None,
    approval: ApprovalRequest | None,
    binding: ProjectRepositoryBinding | None,
) -> datetime:
    """全部锁后取数据库时间，并纳入已持久化资源的时间下界。"""

    values = [effective_job_time(job, database_now)]
    for resource in (candidate, approval, binding):
        if resource is None:
            continue
        for field_name in (
            "created_at",
            "updated_at",
            "approved_at",
            "published_at",
            "decided_at",
            "consumed_at",
        ):
            value = getattr(resource, field_name, None)
            if value is not None:
                values.append(value)
    return max(values)
