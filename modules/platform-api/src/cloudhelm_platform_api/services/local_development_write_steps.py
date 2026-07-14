"""M6 Scaffold 与 Coder 真实工具步骤。"""

from __future__ import annotations

from cloudhelm_agent_runtime.agents import CoderAgent, ScaffoldAgent
from cloudhelm_tool_gateway import ToolGateway
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_result import (
    LocalDevelopmentResult,
)
from cloudhelm_platform_api.services.local_development_step_support import (
    LocalDevelopmentStepSupport,
)
from cloudhelm_platform_api.services.local_development_write_support import (
    build_coder_input,
    build_scaffold_input,
    collect_coder_feedback,
    record_coder_events,
)
from cloudhelm_platform_api.services.local_workspace_resolver import (
    LocalWorkspaceResolver,
)
from cloudhelm_platform_api.services.local_development_tool_policy import (
    coder_tool_calls,
    scaffold_tool_calls,
)


class LocalDevelopmentWriteSteps:
    """运行 Scaffold/Coder，并把真实 workspace/diff 保存为 Artifact。"""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        gateway: ToolGateway,
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway
        self.support = LocalDevelopmentStepSupport(
            session,
            settings,
            gateway,
        )
        self.artifacts = ArtifactService(session, settings)
        self.events = EventService(session)
        self.workspace = LocalWorkspaceResolver(settings)

    def run_scaffold(
        self,
        context: LocalDevelopmentContext,
    ) -> LocalDevelopmentResult:
        """通过 Scaffold Agent 复制 fixture 并初始化 baseline Git。"""

        self.workspace.ensure_configured_roots()
        step = self.support.begin(
            context,
            agent_type="scaffold",
            workflow_step="run_scaffold",
            approved_calls=scaffold_tool_calls(context),
        )
        created_artifacts = []
        try:
            output = ScaffoldAgent(step.provider).run(
                build_scaffold_input(context, self.workspace),
                conversation=step.conversation,
                tools=step.tools,
                tool_executor=step.executor,
            )
            self.support.raise_for_infrastructure(output)
            manifest = self.artifacts.create_json(
                task_id=context.task.id,
                artifact_type="workspace_manifest",
                display_name="workspace-manifest.json",
                content=output.model_dump(mode="json"),
                producer_type=ArtifactProducerType.AGENT,
                summary=output.summary,
                metadata_json={
                    "development_plan_id": str(context.plan.id),
                    "recipe_sha256": context.recipe_sha256,
                    "workspace_key": output.workspace_key,
                    "baseline_commit": output.baseline_commit,
                },
                idempotency_key=f"m6:workspace:{step.run.id}",
                agent_run_id=step.run.id,
            )
            created_artifacts.append(manifest)
            self.support.complete(
                step,
                output,
                output_type="scaffold_agent_output",
            )
            if output.status == "completed":
                self.events.record(
                    "ScaffoldCompleted",
                    "agent",
                    str(step.run.id),
                    {
                        "agent_run_id": str(step.run.id),
                        "artifact_id": str(manifest.id),
                        "baseline_commit": output.baseline_commit,
                    },
                    context.task.id,
                )
            return LocalDevelopmentResult(
                action="run_scaffold",
                message=output.summary,
                target_phase=(
                    "Implementing"
                    if output.status == "completed"
                    else None
                ),
                agent_run=step.run,
                tool_calls=step.executor.tool_calls,
                artifacts=[manifest],
                gate_evidence={
                    "workspace_key": output.workspace_key,
                    "baseline_commit": output.baseline_commit,
                    "recipe_sha256": context.recipe_sha256,
                },
            )
        except Exception as exc:
            self.artifacts.delete_uncommitted_content(created_artifacts)
            self.support.fail(context, step, exc)
            raise

    def run_coder(
        self,
        context: LocalDevelopmentContext,
    ) -> LocalDevelopmentResult:
        """通过 Coder Agent 创建分支、写入 recipe 并生成真实 diff。"""

        self.workspace.workspace(context.task.id)
        step = self.support.begin(
            context,
            agent_type="coder",
            workflow_step="run_coder",
            approved_calls=coder_tool_calls(context, self.workspace),
        )
        created_artifacts = []
        try:
            output = CoderAgent(step.provider).run(
                build_coder_input(
                    context,
                    self.workspace,
                    collect_coder_feedback(self.session, context),
                ),
                conversation=step.conversation,
                tools=step.tools,
                tool_executor=step.executor,
            )
            self.support.raise_for_infrastructure(output)
            diff_call = next(
                (
                    item
                    for item in step.executor.tool_calls
                    if item.tool_name == "git.diff"
                ),
                None,
            )
            if output.status == "completed" and diff_call is None:
                raise ServiceError(
                    "m6_diff_tool_call_missing",
                    "Coder 完成但缺少真实 git.diff ToolCall。",
                    409,
                )
            evidence_set_id = f"m6:{context.plan.id}:{step.run.id}"
            if diff_call is not None:
                details = step.executor.result_json(diff_call)
                patch = details.get("patch")
                if not isinstance(patch, str) or not patch.strip():
                    raise ServiceError(
                        "m6_diff_patch_empty",
                        "Coder git.diff 未返回非空 patch。",
                        409,
                    )
                created_artifacts.append(
                    self.artifacts.create_text(
                        task_id=context.task.id,
                        artifact_type="diff_patch",
                        display_name="implementation.diff",
                        content=patch,
                        producer_type=ArtifactProducerType.TOOL,
                        summary="Coder 真实 workspace diff。",
                        metadata_json={
                            "development_plan_id": str(context.plan.id),
                            "recipe_sha256": context.recipe_sha256,
                            "evidence_set_id": evidence_set_id,
                            "coder_agent_run_id": str(step.run.id),
                            "changed_files": output.diff_paths,
                        },
                        idempotency_key=f"m6:diff:{step.run.id}",
                        tool_call_id=diff_call.id,
                        media_type="text/x-diff",
                    )
                )
            report = self.artifacts.create_json(
                task_id=context.task.id,
                artifact_type="implementation_report",
                display_name="implementation-report.json",
                content=output.model_dump(mode="json"),
                producer_type=ArtifactProducerType.AGENT,
                summary=output.summary,
                metadata_json={
                    "development_plan_id": str(context.plan.id),
                    "recipe_sha256": context.recipe_sha256,
                    "evidence_set_id": evidence_set_id,
                    "status": output.status,
                },
                idempotency_key=f"m6:implementation:{step.run.id}",
                agent_run_id=step.run.id,
            )
            created_artifacts.append(report)
            self.support.complete(
                step,
                output,
                output_type="coder_agent_output",
            )
            record_coder_events(
                self.events,
                context,
                step,
                output,
                created_artifacts,
            )
            return LocalDevelopmentResult(
                action="run_coder",
                message=output.summary,
                target_phase=(
                    "Testing" if output.status == "completed" else None
                ),
                agent_run=step.run,
                tool_calls=step.executor.tool_calls,
                artifacts=created_artifacts,
                gate_evidence={
                    "evidence_set_id": evidence_set_id,
                    "recipe_sha256": context.recipe_sha256,
                    "changed_files": output.diff_paths,
                },
            )
        except Exception as exc:
            self.artifacts.delete_uncommitted_content(created_artifacts)
            self.support.fail(context, step, exc)
            raise
