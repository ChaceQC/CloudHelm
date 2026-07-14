"""M6 Git finalize 的工具执行、commit 验证与失败恢复。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloudhelm_agent_runtime.providers import (
    ProviderToolCall,
    ProviderToolExecutionResult,
)
from sqlalchemy import select

from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead
from cloudhelm_platform_api.services.agent_tool_executor import AgentToolExecutor
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import LocalDevelopmentContext
from cloudhelm_platform_api.services.local_development_git_evidence import ReadyForPrEvidence
from cloudhelm_platform_api.services.local_development_git_utils import (
    gate_error,
    is_git_sha,
    normalize_git_paths,
)
from cloudhelm_platform_api.services.provider_tool_turn import OrchestratedToolTurn


@dataclass(frozen=True, slots=True)
class ExecutedGitCall:
    """一次 Provider call、Gateway 结果与持久化 ToolCall 的精确配对。"""

    result: ProviderToolExecutionResult
    record: ToolCallRead
    evidence_result_json: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CommitPreparation:
    """提交路径以及 commit 后事务失败时的恢复目标。"""

    paths: list[str]
    recovery_commit_sha: str | None = None


class LocalDevelopmentGitExecution:
    """按确定顺序执行 status/diff/commit/format-patch。"""

    def __init__(self, session) -> None:
        self.session = session
        self.agent_runs = AgentRunRepository(session)

    def execute(
        self,
        executor: AgentToolExecutor,
        turn: OrchestratedToolTurn,
        attempt: int,
        tool_name: str,
        arguments: dict[str, Any],
        purpose: str,
    ) -> ExecutedGitCall:
        """执行、精确索引 ToolCall，并追加到当前聚合 turn。"""

        call = ProviderToolCall(
            call_id=(
                f"call_m6_finalize_{attempt}_{tool_name.replace('.', '_')}"
            ),
            name=tool_name,
            arguments=arguments,
        )
        executor.approve_call(tool_name, arguments)
        result = executor(call)
        matches = [
            item
            for item in executor.tool_calls
            if item.provider_call_id == call.call_id
            and item.tool_name == tool_name
        ]
        if len(matches) != 1:
            raise gate_error(
                "m6_tool_call_identity_mismatch",
                f"{tool_name} 未形成唯一持久化 ToolCall。",
            )
        turn.add(call, result, purpose=purpose)
        if result.status != "succeeded":
            raise ServiceError(
                result.error_code or "m6_git_gate_failed",
                str(
                    result.result.get("summary")
                    or f"{tool_name} 执行失败。"
                ),
                409,
            )
        record = matches[0]
        return ExecutedGitCall(
            result=result,
            record=record,
            evidence_result_json=executor.result_json(record),
        )

    def validate_status(
        self,
        result: ProviderToolExecutionResult,
        evidence: ReadyForPrEvidence,
    ) -> None:
        """确认工作区仍位于 Coder 分支且 index 为空。"""

        details = result_details(result)
        if details.get("branch") != evidence.branch_name:
            raise gate_error(
                "m6_workspace_branch_mismatch",
                "当前 Git 分支与 Coder evidence 不一致。",
            )
        staged = normalize_git_paths(
            details.get("staged"),
            "git.status staged",
            False,
        )
        if staged:
            raise gate_error(
                "m6_git_index_not_clean",
                "提交前 Git index 已有调用外暂存内容。",
            )

    def prepare_commit(
        self,
        context: LocalDevelopmentContext,
        evidence: ReadyForPrEvidence,
        status_result: ProviderToolExecutionResult,
        diff_details: dict[str, Any],
        message: str,
    ) -> CommitPreparation:
        """验证当前 diff；clean workspace 只恢复此前真实 commit。"""

        actual = normalize_git_paths(
            diff_details.get("changed_files"),
            "git.diff changed_files",
            False,
        )
        patch = diff_details.get("patch")
        if (
            set(actual) != set(evidence.changed_files)
            or not isinstance(patch, str)
            or not patch.strip()
            or diff_details.get("patch_truncated") is True
            or diff_details.get("from_ref") != evidence.base_commit
            or patch != evidence.diff_text
        ):
            raise gate_error(
                "m6_precommit_diff_mismatch",
                "提交前 baseline diff 与 Coder evidence 不一致。",
            )
        if result_details(status_result).get("clean") is not True:
            return CommitPreparation(paths=evidence.changed_files)
        recovered_sha = self._recoverable_commit_sha(
            context,
            evidence,
            message,
        )
        if recovered_sha is None:
            raise gate_error(
                "m6_git_no_changes",
                "未发现可提交文件或可恢复 commit。",
            )
        return CommitPreparation(
            paths=evidence.changed_files,
            recovery_commit_sha=recovered_sha,
        )

    def validate_commit(
        self,
        result: ProviderToolExecutionResult,
        evidence: ReadyForPrEvidence,
        preparation: CommitPreparation,
    ) -> str:
        """验证 commit SHA、base、paths 和恢复复用语义。"""

        details = result_details(result)
        commit_sha = details.get("commit_hash")
        paths = normalize_git_paths(details.get("paths"), "git.commit paths")
        if (
            not is_git_sha(commit_sha)
            or set(paths) != set(preparation.paths)
        ):
            raise gate_error(
                "m6_commit_evidence_mismatch",
                "Git commit 的 SHA 或 paths 与门禁证据不一致。",
            )
        if preparation.recovery_commit_sha is None:
            if (
                details.get("reused") is not False
                or details.get("base_commit") != evidence.base_commit
            ):
                raise gate_error(
                    "m6_commit_base_mismatch",
                    "新 commit 的 baseline 与 Coder branch 不一致。",
                )
        elif (
            details.get("reused") is not True
            or commit_sha != preparation.recovery_commit_sha
            or details.get("base_commit") is not None
        ):
            raise gate_error(
                "m6_commit_recovery_mismatch",
                "恢复调用未复用先前已成功的同轮 commit。",
            )
        return str(commit_sha)

    @staticmethod
    def validate_patch(
        details: dict[str, Any],
        evidence: ReadyForPrEvidence,
    ) -> tuple[str, dict[str, Any]]:
        """验证 format-patch 完整覆盖当前 changed files。"""

        patch = details.get("patch")
        changed = normalize_git_paths(
            details.get("changed_files"),
            "git.format_patch changed_files",
        )
        if (
            not isinstance(patch, str)
            or not patch.strip()
            or details.get("patch_truncated") is True
            or set(changed) != set(evidence.changed_files)
        ):
            raise gate_error(
                "m6_format_patch_invalid",
                "git.format_patch 未完整覆盖当前 evidence set。",
            )
        return patch, details

    def _recoverable_commit_sha(
        self,
        context: LocalDevelopmentContext,
        evidence: ReadyForPrEvidence,
        message: str,
    ) -> str | None:
        """查找 Coder 完成后已成功但尚未收尾的真实 commit。"""

        coder_finished = evidence.implementation.run.finished_at
        if coder_finished is None:
            return None
        statement = (
            select(ToolCall)
            .where(
                ToolCall.task_id == context.task.id,
                ToolCall.tool_name == "git.commit",
                ToolCall.status == "succeeded",
            )
            .order_by(ToolCall.started_at.desc(), ToolCall.id.desc())
        )
        for call in self.session.scalars(statement):
            if call.agent_run_id is None:
                continue
            run = self.agent_runs.get(call.agent_run_id)
            if (
                run is None
                or run.workflow_step != "finalize_local_pull_request"
                or run.started_at < coder_finished
            ):
                continue
            details = call.result_json or {}
            paths = normalize_git_paths(
                details.get("paths"),
                "historical git.commit paths",
                False,
            )
            arguments = normalize_git_paths(
                call.arguments_json.get("paths"),
                "historical git.commit arguments",
                False,
            )
            if (
                is_git_sha(details.get("commit_hash"))
                and details.get("base_commit") == evidence.base_commit
                and set(paths) == set(evidence.changed_files)
                and set(arguments) == set(evidence.changed_files)
                and call.arguments_json.get("message") == message
            ):
                return str(details["commit_hash"])
        return None


def result_details(result: ProviderToolExecutionResult) -> dict[str, Any]:
    """读取 Tool Gateway 的结构化 result_json。"""

    details = result.result.get("result_json")
    return details if isinstance(details, dict) else {}


def commit_message(title: str) -> str:
    """从 Task title 派生稳定、可恢复匹配的 commit message。"""

    return f"feat: {title.strip()}"[:200]
