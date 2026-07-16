"""M7 ReleaseCandidate canonical identity、ref 与审批策略。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re
from uuid import UUID

from cloudhelm_platform_api.core.repository_config import (
    validate_git_head_ref,
)
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.services.repository_binding_snapshot import (
    internal_snapshot_hash_from_binding,
    public_snapshot_from_binding,
)
from cloudhelm_tool_gateway.audit import stable_json_hash

APPROVAL_ACTION = "approve_release_candidate"
APPROVAL_TTL = timedelta(hours=24)
CANDIDATE_REQUEST_SCHEMA = "m7.release-candidate.request.v1"
RECONCILE_JOB_TYPE = "release_candidate_reconcile"
RECONCILE_JOB_REQUEST_SCHEMA = (
    "m7.workflow-job.release-candidate-reconcile.v1"
)
RECONCILE_PAYLOAD_SCHEMA = "m7.release-candidate-reconcile.payload.v1"
_HASH_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")


@dataclass(frozen=True)
class ReleaseCandidateIdentity:
    """由 Task、PR 与 Binding 唯一派生的 Candidate 身份。"""

    public_snapshot: dict[str, str]
    binding_snapshot_sha256: str
    target_ref: str
    canonical_request: dict[str, str]
    request_hash: str
    idempotency_key: str


@dataclass(frozen=True)
class ReconcileJobSpec:
    """无外部副作用 reconcile job 的严格 canonical 与 payload。"""

    canonical_request: dict[str, str]
    request_hash: str
    idempotency_key: str
    payload: dict[str, str]


def build_release_candidate_identity(
    *,
    binding: ProjectRepositoryBinding,
    task_id: UUID,
    project_id: UUID,
    pull_request_record_id: UUID,
    commit_sha: str,
) -> ReleaseCandidateIdentity:
    """按冻结契约生成 snapshot、target ref、request hash 与幂等键。"""

    public_snapshot = public_snapshot_from_binding(binding)
    snapshot_hash = internal_snapshot_hash_from_binding(binding)
    snapshot_hex = _hash_hex(snapshot_hash)
    target_ref = (
        f"{binding.release_ref_prefix}/{task_id}/{commit_sha}/"
        f"{snapshot_hex}"
    )
    validate_git_head_ref(target_ref, max_length=1024)
    canonical = {
        "schema_version": CANDIDATE_REQUEST_SCHEMA,
        "action": APPROVAL_ACTION,
        "task_id": str(task_id),
        "project_id": str(project_id),
        "pull_request_record_id": str(pull_request_record_id),
        "repository_binding_id": str(binding.id),
        "binding_snapshot_sha256": snapshot_hash,
        "commit_sha": commit_sha,
        "target_ref": target_ref,
    }
    request_hash = stable_json_hash(canonical)
    return ReleaseCandidateIdentity(
        public_snapshot=public_snapshot,
        binding_snapshot_sha256=snapshot_hash,
        target_ref=target_ref,
        canonical_request=canonical,
        request_hash=request_hash,
        idempotency_key=(
            f"release_candidate:v1:{_hash_hex(request_hash)}"
        ),
    )


def build_reconcile_job_spec(
    *,
    candidate_id: UUID,
    approval_id: UUID,
    pull_request_record_id: UUID,
    candidate_request_hash: str,
    binding_snapshot_sha256: str,
) -> ReconcileJobSpec:
    """生成 release_candidate_reconcile 的严格 job identity。"""

    canonical = {
        "schema_version": RECONCILE_JOB_REQUEST_SCHEMA,
        "job_type": RECONCILE_JOB_TYPE,
        "resource_type": "release_candidate",
        "resource_id": str(candidate_id),
        "candidate_request_hash": candidate_request_hash,
        "approval_id": str(approval_id),
    }
    request_hash = stable_json_hash(canonical)
    return ReconcileJobSpec(
        canonical_request=canonical,
        request_hash=request_hash,
        idempotency_key=(
            f"release_candidate_reconcile:v1:{_hash_hex(request_hash)}"
        ),
        payload={
            "schema_version": RECONCILE_PAYLOAD_SCHEMA,
            "candidate_id": str(candidate_id),
            "approval_id": str(approval_id),
            "expected_candidate_request_hash": candidate_request_hash,
            "expected_binding_snapshot_sha256": (
                binding_snapshot_sha256
            ),
            "expected_pull_request_record_id": str(
                pull_request_record_id
            ),
        },
    )


def normalize_actor_agent_run_id(actor_id: str) -> UUID | None:
    """解析 plain UUID 或 `agent-run:<UUID>`，其他用户标识返回空。"""

    normalized = actor_id.strip()
    if normalized.startswith("agent-run:"):
        normalized = normalized.removeprefix("agent-run:")
    try:
        return UUID(normalized)
    except ValueError:
        return None


def _hash_hex(value: str) -> str:
    """读取统一 `sha256:` 字符串的 64 位小写 hex。"""

    match = _HASH_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("M7 hash 格式非法。")
    return match.group(1)
