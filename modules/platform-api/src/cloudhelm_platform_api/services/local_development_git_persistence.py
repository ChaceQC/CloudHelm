"""M6 Git finalize 的 patch Artifact 与 local PR record 持久化。"""

from __future__ import annotations

from typing import Any

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.schemas.artifact import (
    ArtifactProducerType,
    ArtifactStatus,
)
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestProvider,
    PullRequestRecordCreate,
)
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_git_evidence import (
    ReadyForPrEvidence,
)
from cloudhelm_platform_api.services.local_development_git_utils import (
    gate_error,
    read_artifact_text,
)
from cloudhelm_platform_api.services.pull_request_record_service import (
    PullRequestRecordService,
)


class LocalDevelopmentGitPersistence:
    """保存 format-patch，并创建或复用唯一 local PR record。"""

    def __init__(self, session, settings: Settings) -> None:
        self.artifact_service = ArtifactService(session, settings)
        self.artifacts = ArtifactRepository(session)
        self.records = PullRequestRecordService(session)

    def patch_artifact(
        self,
        context: LocalDevelopmentContext,
        evidence: ReadyForPrEvidence,
        patch_call: ToolCallRead,
        commit_sha: str,
        patch_text: str,
    ) -> tuple[Artifact, bool]:
        """创建或复用同 evidence set 的唯一 format-patch Artifact。"""

        evidence_set_id = evidence.implementation.evidence_set_id
        key = f"m6:format-patch:{evidence_set_id}"
        metadata = {
            "base_branch": context.project.default_branch,
            "head_branch": evidence.branch_name,
            "base_commit_sha": evidence.base_commit,
            "commit_sha": commit_sha,
            "development_plan_id": str(context.plan.id),
            "evidence_set_id": evidence_set_id,
            "coder_agent_run_id": str(evidence.implementation.run.id),
            "recipe_sha256": context.recipe_sha256,
        }
        existing = self.artifacts.get_by_task_idempotency_key(
            context.task.id,
            key,
        )
        if existing is not None:
            stored = read_artifact_text(
                self.artifact_service.storage,
                existing,
                "format-patch Artifact",
            )
            if (
                existing.artifact_type != "format_patch"
                or existing.status != ArtifactStatus.AVAILABLE.value
                or existing.metadata_json != metadata
                or stored != patch_text
            ):
                raise gate_error(
                    "m6_format_patch_idempotency_conflict",
                    "同一 evidence set 的 format-patch 内容冲突。",
                )
            return existing, False
        artifact = self.artifact_service.create_text(
            task_id=context.task.id,
            artifact_type="format_patch",
            display_name=f"{commit_sha[:12]}.patch",
            content=patch_text,
            producer_type=ArtifactProducerType.TOOL,
            summary="本地 commit 的可审计 format-patch。",
            metadata_json=metadata,
            idempotency_key=key,
            tool_call_id=patch_call.id,
            media_type="text/x-diff",
        )
        return artifact, True

    def create_pr_record(
        self,
        context: LocalDevelopmentContext,
        evidence: ReadyForPrEvidence,
        run_id,
        commit_call: ToolCallRead,
        patch_artifact: Artifact,
        commit_sha: str,
        paths: list[str],
        patch_details: dict[str, Any],
    ):
        """创建或复用与 evidence/commit 精确一致的 local PR record。"""

        changed_by_path = {
            item.path: item
            for item in evidence.implementation.output.changed_files
        }
        record = self.records.create(
            PullRequestRecordCreate(
                task_id=context.task.id,
                project_id=context.task.project_id,
                development_plan_id=context.plan.id,
                created_by_agent_run_id=run_id,
                branch_tool_call_id=evidence.branch_call.id,
                commit_tool_call_id=commit_call.id,
                provider=PullRequestProvider.LOCAL,
                title=f"{context.task.title}（本地等价 PR）",
                summary=(
                    "真实 diff、pytest、review、安全扫描与本地 commit "
                    "均已通过 M6 门禁。"
                ),
                base_branch=context.project.default_branch,
                head_branch=evidence.branch_name,
                base_commit_sha=evidence.base_commit,
                commit_sha=commit_sha,
                changed_files_json=[
                    {
                        "path": path,
                        "operation": changed_by_path[path].operation,
                        "intent": changed_by_path[path].intent,
                    }
                    for path in paths
                ],
                diff_stat_json={
                    "text": str(patch_details.get("stat") or "")
                },
                diff_artifact_id=patch_artifact.id,
                test_artifact_id=evidence.test_artifact.id,
                review_artifact_id=evidence.review_artifact.id,
                security_artifact_id=evidence.security_artifact.id,
                url=None,
                idempotency_key=(
                    "m6:local-pr:"
                    f"{evidence.implementation.evidence_set_id}"
                ),
            )
        )
        if (
            record.development_plan_id != context.plan.id
            or record.commit_sha != commit_sha
            or record.base_commit_sha != evidence.base_commit
            or record.base_branch != context.project.default_branch
            or record.head_branch != evidence.branch_name
            or record.diff_artifact_id != patch_artifact.id
            or record.test_artifact_id != evidence.test_artifact.id
            or record.review_artifact_id != evidence.review_artifact.id
            or record.security_artifact_id != evidence.security_artifact.id
        ):
            raise gate_error(
                "m6_existing_pr_record_mismatch",
                "既有 local PR record 与当前 evidence set 不一致。",
            )
        return record

    def delete_uncommitted_content(
        self,
        artifacts: list[Artifact],
    ) -> None:
        """删除回滚事务对应的物理 Artifact 文件。"""

        self.artifact_service.delete_uncommitted_content(artifacts)
