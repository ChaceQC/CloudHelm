"""M7 ReleaseCandidate API DTO 与安全转换。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.schemas.common import ApprovalStatus


class ReleaseCandidateCreate(BaseModel):
    """Candidate 创建只接受 JSON 空对象。"""

    model_config = ConfigDict(extra="forbid")


class RepositoryBindingSnapshotRead(BaseModel):
    """Candidate 可公开的精确八字段 RepositoryBinding snapshot。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["m7.repository-binding.snapshot.v1"]
    provider: Literal["gitea"]
    repository_external_id: str
    repository_owner: str
    repository_name: str
    default_branch: str
    workflow_id: str
    release_ref_prefix: str


class ReleaseCandidateStatus(str, Enum):
    """ReleaseCandidate 生命周期状态。"""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    STALE = "stale"
    CANCELLED = "cancelled"


class ReleaseCandidateRead(BaseModel):
    """不暴露 clone URL、profile 或 credential 的 Candidate 响应。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    task_id: UUID
    project_id: UUID
    pull_request_record_id: UUID
    repository_binding_id: UUID
    binding_snapshot: RepositoryBindingSnapshotRead
    binding_snapshot_sha256: str
    commit_sha: str
    target_ref: str
    request_hash: str
    status: ReleaseCandidateStatus
    approval_id: UUID
    remote_verified_sha: str | None
    idempotency_key: str
    approved_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReleaseCandidateApprovalRead(BaseModel):
    """Candidate envelope 中的最小审批摘要。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    action: Literal["approve_release_candidate"]
    risk_level: Literal["L2"]
    resource_type: Literal["release_candidate"]
    resource_id: UUID
    status: ApprovalStatus
    requested_by_agent_run_id: UUID
    request_hash: str
    expires_at: datetime
    consumed_at: datetime | None


class ReleaseCandidateEnvelope(BaseModel):
    """Candidate 与其第一道审批的原子 public envelope。"""

    model_config = ConfigDict(extra="forbid")

    candidate: ReleaseCandidateRead
    approval: ReleaseCandidateApprovalRead


def release_candidate_to_read(
    candidate: ReleaseCandidate,
) -> ReleaseCandidateRead:
    """把 ORM Candidate 转为严格 public DTO。"""

    return ReleaseCandidateRead(
        id=candidate.id,
        task_id=candidate.task_id,
        project_id=candidate.project_id,
        pull_request_record_id=candidate.pull_request_record_id,
        repository_binding_id=candidate.repository_binding_id,
        binding_snapshot=RepositoryBindingSnapshotRead.model_validate(
            candidate.binding_snapshot_json
        ),
        binding_snapshot_sha256=candidate.binding_snapshot_sha256,
        commit_sha=candidate.commit_sha,
        target_ref=candidate.target_ref,
        request_hash=candidate.request_hash,
        status=ReleaseCandidateStatus(candidate.status),
        approval_id=candidate.approval_id,
        remote_verified_sha=candidate.remote_verified_sha,
        idempotency_key=candidate.idempotency_key,
        approved_at=candidate.approved_at,
        published_at=candidate.published_at,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def release_candidate_approval_to_read(
    approval: ApprovalRequest,
) -> ReleaseCandidateApprovalRead:
    """把资源审批转换为不含 reason/decider 的 Candidate 摘要。"""

    assert approval.resource_id is not None
    assert approval.requested_by_agent_run_id is not None
    assert approval.request_hash is not None
    assert approval.expires_at is not None
    return ReleaseCandidateApprovalRead(
        id=approval.id,
        action="approve_release_candidate",
        risk_level="L2",
        resource_type="release_candidate",
        resource_id=approval.resource_id,
        status=ApprovalStatus(approval.status),
        requested_by_agent_run_id=approval.requested_by_agent_run_id,
        request_hash=approval.request_hash,
        expires_at=approval.expires_at,
        consumed_at=approval.consumed_at,
    )
