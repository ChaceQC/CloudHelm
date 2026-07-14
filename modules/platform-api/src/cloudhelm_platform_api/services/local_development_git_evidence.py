"""M6 Git finalize 的同轮证据与 branch baseline 门禁。"""

from __future__ import annotations

from dataclasses import dataclass

from cloudhelm_tool_gateway.audit import redact_sensitive_text

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_evidence import (
    ImplementationEvidence,
    LocalDevelopmentEvidenceResolver,
)
from cloudhelm_platform_api.services.local_development_git_quality_gate import (
    LocalDevelopmentGitQualityGate,
)
from cloudhelm_platform_api.services.local_development_git_utils import (
    gate_error,
    is_git_sha,
    normalize_git_paths,
    read_artifact_text,
)
from cloudhelm_platform_api.services.local_workspace_resolver import (
    LocalWorkspaceResolver,
)


@dataclass(frozen=True, slots=True)
class ReadyForPrEvidence:
    """同一 Coder cycle 的四类门禁与 Git branch 基线。"""

    implementation: ImplementationEvidence
    test_artifact: Artifact
    review_artifact: Artifact
    security_artifact: Artifact
    branch_call: ToolCall
    branch_name: str
    base_commit: str
    changed_files: list[str]
    diff_text: str


class LocalDevelopmentGitEvidenceGate:
    """重读最新成功 Coder、真实 diff 与三类质量结论。"""

    def __init__(self, session, settings: Settings) -> None:
        self.tool_calls = ToolCallRepository(session)
        self.evidence = LocalDevelopmentEvidenceResolver(session)
        self.artifacts = ArtifactService(session, settings)
        self.quality = LocalDevelopmentGitQualityGate(session)
        self.workspace = LocalWorkspaceResolver(settings)

    def resolve(
        self,
        context: LocalDevelopmentContext,
    ) -> ReadyForPrEvidence:
        """返回 commit 前经过严格交叉校验的同轮证据。"""

        implementation = self.evidence.implementation(context)
        output = implementation.output
        expected_branch = self.workspace.branch_name(context.task.id)
        if output.task_id != context.task.id:
            raise gate_error("m6_coder_task_mismatch", "Coder 输出 Task 无效。")
        if output.branch_name != expected_branch:
            raise gate_error(
                "m6_coder_branch_mismatch",
                "Coder 输出分支与平台绑定分支不一致。",
            )
        changed_files = normalize_git_paths(
            output.diff_paths,
            "Coder diff_paths",
        )
        output_files = normalize_git_paths(
            [item.path for item in output.changed_files],
            "Coder changed_files",
        )
        if set(changed_files) != set(output_files):
            raise gate_error(
                "m6_coder_changed_files_mismatch",
                "Coder diff_paths 与 changed_files 不一致。",
            )

        calls = self.tool_calls.list_by_agent_run(implementation.run.id)
        branch_calls = _calls(calls, "git.create_branch")
        diff_calls = _calls(calls, "git.diff")
        if len(branch_calls) != 1 or len(diff_calls) != 1:
            raise gate_error(
                "m6_coder_git_evidence_ambiguous",
                "Coder run 必须精确对应一个 branch 和一个 diff ToolCall。",
            )
        branch_call = branch_calls[0]
        branch_details = branch_call.result_json or {}
        base_commit = branch_details.get("base_commit")
        if (
            branch_details.get("branch_name") != expected_branch
            or branch_call.arguments_json.get("branch_name")
            != expected_branch
            or not is_git_sha(base_commit)
        ):
            raise gate_error(
                "m6_branch_base_mismatch",
                "Coder branch 或 baseline commit 无效。",
            )
        diff_text = self._validate_diff(
            implementation,
            diff_calls[0],
            changed_files,
        )

        evidence_set_id = implementation.evidence_set_id
        test = self.evidence.required_artifact(
            context,
            "test_report",
            evidence_set_id,
        )
        review = self.evidence.required_artifact(
            context,
            "review_report",
            evidence_set_id,
        )
        security = self.evidence.required_artifact(
            context,
            "security_report",
            evidence_set_id,
        )
        self.quality.validate(
            context,
            implementation,
            test,
            review,
            security,
        )
        return ReadyForPrEvidence(
            implementation=implementation,
            test_artifact=test,
            review_artifact=review,
            security_artifact=security,
            branch_call=branch_call,
            branch_name=expected_branch,
            base_commit=str(base_commit),
            changed_files=changed_files,
            diff_text=diff_text,
        )

    def _validate_diff(
        self,
        implementation: ImplementationEvidence,
        diff_call: ToolCall,
        changed_files: list[str],
    ) -> str:
        """验证 Coder ToolCall、Artifact 内容和 changed files 完全一致。"""

        details = diff_call.result_json or {}
        patch = details.get("patch")
        actual = normalize_git_paths(
            details.get("changed_files"),
            "Coder git.diff changed_files",
        )
        artifact = implementation.diff_artifact
        metadata_files = normalize_git_paths(
            artifact.metadata_json.get("changed_files"),
            "diff Artifact changed_files",
        )
        stored = read_artifact_text(
            self.artifacts.storage,
            artifact,
            "diff Artifact",
        )
        if (
            artifact.tool_call_id != diff_call.id
            or not isinstance(patch, str)
            or not patch.strip()
            or details.get("patch_truncated") is True
            or set(actual) != set(changed_files)
            or set(metadata_files) != set(changed_files)
            or stored != (redact_sensitive_text(patch) or "")
        ):
            raise gate_error(
                "m6_coder_diff_invalid",
                "Coder run 缺少完整且非空的真实 diff。",
            )
        return stored

def _calls(calls: list[ToolCall], tool_name: str) -> list[ToolCall]:
    """过滤一个 Coder run 中指定名称的成功 ToolCall。"""

    return [
        call
        for call in calls
        if call.tool_name == tool_name and call.status == "succeeded"
    ]
