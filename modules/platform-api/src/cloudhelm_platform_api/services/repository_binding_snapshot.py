"""M7 RepositoryBinding 安全快照与内部 freshness hash。"""

from typing import Any

from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_tool_gateway.audit import stable_json_hash

PUBLIC_SNAPSHOT_SCHEMA = "m7.repository-binding.snapshot.v1"
INTERNAL_SNAPSHOT_SCHEMA = "m7.repository-binding.internal-snapshot.v1"


def build_repository_binding_public_snapshot(
    *,
    provider: str,
    repository_external_id: str,
    repository_owner: str,
    repository_name: str,
    default_branch: str,
    workflow_id: str,
    release_ref_prefix: str,
) -> dict[str, str]:
    """构造精确八字段、可进入 API/Event/Candidate 的安全快照。"""

    return {
        "schema_version": PUBLIC_SNAPSHOT_SCHEMA,
        "provider": provider,
        "repository_external_id": repository_external_id,
        "repository_owner": repository_owner,
        "repository_name": repository_name,
        "default_branch": default_branch,
        "workflow_id": workflow_id,
        "release_ref_prefix": release_ref_prefix,
    }


def repository_binding_internal_snapshot_hash(
    *,
    public_snapshot: dict[str, str],
    profile_key: str,
    clone_url: str,
    credential_ref: str,
) -> str:
    """对公开快照和三项内部配置生成统一稳定 hash。"""

    internal_snapshot: dict[str, Any] = {
        "schema_version": INTERNAL_SNAPSHOT_SCHEMA,
        "public_snapshot": public_snapshot,
        "profile_key": profile_key,
        "clone_url": clone_url,
        "credential_ref": credential_ref,
    }
    return stable_json_hash(internal_snapshot)


def public_snapshot_from_binding(
    binding: ProjectRepositoryBinding,
) -> dict[str, str]:
    """从已物化 Binding 读取安全快照。"""

    return build_repository_binding_public_snapshot(
        provider=binding.provider,
        repository_external_id=binding.repository_external_id,
        repository_owner=binding.repository_owner,
        repository_name=binding.repository_name,
        default_branch=binding.default_branch,
        workflow_id=binding.workflow_id,
        release_ref_prefix=binding.release_ref_prefix,
    )


def internal_snapshot_hash_from_binding(
    binding: ProjectRepositoryBinding,
) -> str:
    """从已物化 Binding 重算内部 freshness hash。"""

    return repository_binding_internal_snapshot_hash(
        public_snapshot=public_snapshot_from_binding(binding),
        profile_key=binding.profile_key,
        clone_url=binding.clone_url,
        credential_ref=binding.credential_ref,
    )
