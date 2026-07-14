"""M6 ReadyForPR 的真实 Git、patch 与本地 PR record 收尾。"""

from __future__ import annotations

from cloudhelm_tool_gateway import ToolGateway

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.services.agent_conversation_service import AgentConversationService
from cloudhelm_platform_api.services.agent_provider_factory import AgentProviderFactory
from cloudhelm_platform_api.services.agent_run_lifecycle import AgentRunLifecycle
from cloudhelm_platform_api.services.agent_tool_executor import AgentToolExecutor
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.local_development_context import LocalDevelopmentContext
from cloudhelm_platform_api.services.local_development_git_evidence import LocalDevelopmentGitEvidenceGate
from cloudhelm_platform_api.services.local_development_git_execution import (
    LocalDevelopmentGitExecution,
    commit_message,
)
from cloudhelm_platform_api.services.local_development_git_persistence import LocalDevelopmentGitPersistence
from cloudhelm_platform_api.services.local_development_result import LocalDevelopmentResult
from cloudhelm_platform_api.services.provider_tool_turn import OrchestratedToolTurn


class LocalDevelopmentGitService:
    """聚合四次 Git 调用，并在同一业务事务内形成等价 PR。"""

    def __init__(
        self,
        session,
        settings: Settings,
        gateway: ToolGateway,
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway
        self.provider_factory = AgentProviderFactory(settings)
        self.lifecycle = AgentRunLifecycle(session, settings)
        self.conversations = AgentConversationService(session, settings)
        self.evidence = LocalDevelopmentGitEvidenceGate(session, settings)
        self.git = LocalDevelopmentGitExecution(session)
        self.persistence = LocalDevelopmentGitPersistence(session, settings)
        self.events = EventService(session)

    def finalize(
        self,
        context: LocalDevelopmentContext,
    ) -> LocalDevelopmentResult:
        """重新验证同轮证据后提交，并恢复 commit 后的事务失败。"""

        task = context.task
        run = self.lifecycle.claim_or_start(
            task,
            "coder",
            workflow_step="finalize_local_pull_request",
        )
        self.session.commit()
        created_artifacts: list[Artifact] = []
        conversation_record = None
        conversation = None
        expected_revision = None
        turn = None
        turn_committed = False
        try:
            evidence = self.evidence.resolve(context)
            provider = self.provider_factory.create()
            conversation_record, conversation = (
                self.conversations.load_or_create_root(
                    task,
                    provider_name=provider.name,
                    model_name=provider.model_name,
                )
            )
            expected_revision = conversation_record.revision
            executor = AgentToolExecutor(
                self.session,
                self.gateway,
                self.settings,
                task_id=task.id,
                agent_run_id=run.id,
                workflow_step=run.workflow_step
                or "finalize_local_pull_request",
                attempt=run.attempt or 1,
            )
            turn = OrchestratedToolTurn(
                agent_type="coder",
                step_name="finalize_local_pull_request",
                step_purpose=(
                    "复核同轮质量证据，并完成 Git 提交和 format-patch。"
                ),
            )
            status = self.git.execute(
                executor,
                turn,
                run.attempt or 1,
                "git.status",
                {},
                "提交前确认当前分支和 index 状态。",
            )
            self.git.validate_status(status.result, evidence)
            diff = self.git.execute(
                executor,
                turn,
                run.attempt or 1,
                "git.diff",
                {
                    "include_untracked": True,
                    "from_ref": evidence.base_commit,
                },
                "从 Coder baseline 读取待提交真实 diff。",
            )
            evidence = self.evidence.resolve(context)
            self.git.validate_status(status.result, evidence)
            message = commit_message(task.title)
            preparation = self.git.prepare_commit(
                context,
                evidence,
                status.result,
                diff.evidence_result_json,
                message,
            )
            commit = self.git.execute(
                executor,
                turn,
                run.attempt or 1,
                "git.commit",
                {
                    "message": message,
                    "paths": preparation.paths,
                },
                "提交当前 evidence set 的显式 changed files。",
            )
            commit_sha = self.git.validate_commit(
                commit.result,
                evidence,
                preparation,
            )
            patch = self.git.execute(
                executor,
                turn,
                run.attempt or 1,
                "git.format_patch",
                {
                    "base_ref": context.project.default_branch,
                    "head_ref": "HEAD",
                },
                "生成本地等价 PR 的完整 format-patch。",
            )
            patch_text, patch_details = self.git.validate_patch(
                patch.evidence_result_json,
                evidence,
            )
            turn.commit(
                conversation,
                summary=(
                    f"Git 门禁通过并形成 commit {commit_sha[:12]}、"
                    "format-patch 与本地等价 PR 证据。"
                ),
            )
            turn_committed = True

            patch_artifact, created = self.persistence.patch_artifact(
                context,
                evidence,
                patch.record,
                commit_sha,
                patch_text,
            )
            if created:
                created_artifacts.append(patch_artifact)
            record = self.persistence.create_pr_record(
                context,
                evidence,
                run.id,
                commit.record,
                patch_artifact,
                commit_sha,
                preparation.paths,
                patch_details,
            )
            output = self._output(
                context,
                evidence,
                record,
                commit_sha,
                preparation,
            )
            self.lifecycle.complete(
                run,
                "已创建本地 commit、format-patch 与等价 PR record。",
                "local_pull_request_finalization",
                output,
                conversation=conversation,
            )
            self.conversations.save_turn(
                conversation_record,
                conversation,
                None,
                expected_revision=expected_revision,
            )
            if record.created_by_agent_run_id == run.id:
                self.events.record(
                    "CommitCreated",
                    "agent",
                    str(run.id),
                    {
                        "commit_sha": commit_sha,
                        "tool_call_id": str(commit.record.id),
                        "evidence_set_id": (
                            evidence.implementation.evidence_set_id
                        ),
                    },
                    task.id,
                )
            return LocalDevelopmentResult(
                action="finalize_local_pull_request",
                message="已创建真实本地 commit、patch 与 local PR record。",
                target_phase="PullRequestCreated",
                agent_run=run,
                tool_calls=executor.tool_calls,
                artifacts=[patch_artifact],
                pull_request_record=record,
                gate_evidence=output,
            )
        except Exception as exc:
            self.session.rollback()
            self.persistence.delete_uncommitted_content(created_artifacts)
            self._save_failed_turn(
                conversation_record,
                conversation,
                expected_revision,
                turn,
                turn_committed,
                exc,
            )
            self.lifecycle.fail(task, run, exc)
    @staticmethod
    def _output(
        context,
        evidence,
        record,
        commit_sha,
        preparation,
    ) -> dict:
        """构造 AgentRun 与 API 共用的稳定收尾摘要。"""

        return {
            "commit_sha": commit_sha,
            "base_commit_sha": evidence.base_commit,
            "branch_name": evidence.branch_name,
            "changed_files": preparation.paths,
            "evidence_set_id": evidence.implementation.evidence_set_id,
            "pull_request_record_id": str(record.id),
            "recipe_sha256": context.recipe_sha256,
            "recovered_commit": (
                preparation.recovery_commit_sha is not None
            ),
        }

    def _save_failed_turn(
        self,
        record,
        conversation,
        expected_revision,
        turn,
        turn_committed: bool,
        exc: Exception,
    ) -> None:
        """尽力保存一个失败 turn，不掩盖原始异常。"""

        if (
            record is None
            or conversation is None
            or expected_revision is None
            or turn is None
            or turn.call_count == 0
        ):
            return
        try:
            if not turn_committed:
                turn.commit(
                    conversation,
                    summary=(
                        "Git finalize 未完成："
                        f"{getattr(exc, 'code', type(exc).__name__)}。"
                    ),
                )
            self.conversations.save_turn(
                record,
                conversation,
                None,
                expected_revision=expected_revision,
            )
        except Exception:
            self.session.rollback()
