"""M6 Agent 单步执行的共享生命周期、conversation 与工具上下文。"""

from __future__ import annotations

from dataclasses import dataclass
import json

from pydantic import BaseModel
from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.providers import (
    ProviderConversation,
    ProviderToolCall,
    ProviderToolExecutionResult,
)
from cloudhelm_agent_runtime.providers.contracts import developer_message_item
from cloudhelm_tool_gateway import ToolGateway

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from cloudhelm_platform_api.services.agent_provider_factory import (
    AgentProviderFactory,
)
from cloudhelm_platform_api.services.agent_run_lifecycle import (
    RECOVERABLE_SERVICE_ERROR_CODES,
    AgentRunLifecycle,
)
from cloudhelm_platform_api.services.agent_tool_executor import AgentToolExecutor
from cloudhelm_platform_api.services.agent_tool_manifest import (
    build_provider_tool_manifest,
)
from cloudhelm_platform_api.services.artifact_storage import (
    discard_pending_artifacts,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.provider_tool_turn import (
    OrchestratedToolTurn,
)
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)


@dataclass(slots=True)
class RunningLocalAgentStep:
    """一个已抢占 AgentRun、尚未提交最终产物的 M6 步骤。"""

    run: AgentRun
    provider: object
    conversation_record: AgentConversation
    conversation: ProviderConversation
    expected_revision: int
    initial_turn_count: int
    executor: AgentToolExecutor
    tools: tuple


class LocalDevelopmentStepSupport:
    """集中处理 M6 AgentRun 短事务、root conversation 和失败分类。"""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        gateway: ToolGateway,
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway
        self.provider_factory = AgentProviderFactory(settings)
        self.lifecycle = AgentRunLifecycle(session, settings)
        self.conversations = AgentConversationService(session, settings)

    def begin(
        self,
        context: LocalDevelopmentContext,
        *,
        agent_type: str,
        workflow_step: str,
        approved_calls: tuple | list,
    ) -> RunningLocalAgentStep:
        """短事务创建 running AgentRun，再准备共享 root conversation。"""

        run = self.lifecycle.claim_or_start(
            context.task,
            agent_type,
            workflow_step=workflow_step,
        )
        self.session.commit()
        provider = self.provider_factory.create()
        record, conversation = self.conversations.load_or_create_root(
            context.task,
            provider_name=provider.name,
            model_name=provider.model_name,
        )
        expected_revision = record.revision
        self.session.commit()
        return RunningLocalAgentStep(
            run=run,
            provider=provider,
            conversation_record=record,
            conversation=conversation,
            expected_revision=expected_revision,
            initial_turn_count=conversation.turn_count,
            executor=AgentToolExecutor(
                self.session,
                self.gateway,
                self.settings,
                task_id=context.task.id,
                agent_run_id=run.id,
                workflow_step=workflow_step,
                attempt=run.attempt or 1,
                approved_calls=approved_calls,
            ),
            tools=build_provider_tool_manifest(self.gateway),
        )

    def complete(
        self,
        step: RunningLocalAgentStep,
        output: BaseModel,
        *,
        output_type: str,
    ) -> None:
        """校验基础设施状态并原子保存 AgentRun 与 conversation。"""

        self.raise_for_infrastructure(output)
        summary = str(getattr(output, "summary", "M6 Agent 已完成。"))
        self.lifecycle.complete(
            step.run,
            summary,
            output_type,
            output.model_dump(mode="json"),
            step.provider.last_call_metadata,
            step.conversation,
        )
        self.conversations.save_turn(
            step.conversation_record,
            step.conversation,
            step.provider.last_call_metadata,
            expected_revision=step.expected_revision,
        )

    def fail(
        self,
        context: LocalDevelopmentContext,
        step: RunningLocalAgentStep,
        exc: Exception,
    ) -> None:
        """按 M6 可恢复错误映射记录失败并提交。"""

        self.session.rollback()
        discard_pending_artifacts(self.session)
        self._save_failed_turn(step, exc)
        self.lifecycle.fail(context.task, step.run, exc)

    def _save_failed_turn(
        self,
        step: RunningLocalAgentStep,
        exc: Exception,
    ) -> None:
        """尽力保存真实 call/output 与下一次重试需要的失败上下文。"""

        try:
            if (
                step.conversation.turn_count == step.initial_turn_count
                and step.executor.tool_calls
            ):
                self._rebuild_failed_tool_turn(step, exc)
            feedback = {
                "schema_version": "m6-failed-step-v1",
                "agent_run_id": str(step.run.id),
                "workflow_step": step.run.workflow_step,
                "attempt": step.run.attempt,
                "error_code": getattr(exc, "code", type(exc).__name__),
                "tool_call_ids": [
                    str(item.id) for item in step.executor.tool_calls
                ],
            }
            step.conversation.append_context_item(
                developer_message_item(
                    "<failed_step_context>\n"
                    f"{json.dumps(feedback, ensure_ascii=False, sort_keys=True)}"
                    "\n</failed_step_context>"
                )
            )
            self.conversations.save_turn(
                step.conversation_record,
                step.conversation,
                step.provider.last_call_metadata,
                expected_revision=step.expected_revision,
            )
            step.run.conversation_id = step.conversation_record.id
            step.run.conversation_turn = step.conversation.turn_count
        except Exception:
            self.session.rollback()

    def _rebuild_failed_tool_turn(
        self,
        step: RunningLocalAgentStep,
        exc: Exception,
    ) -> None:
        """在 Provider 未提交 pending turn 时从持久化 ToolCall 重建配对证据。"""

        repository = ToolCallRepository(self.session)
        turn = OrchestratedToolTurn(
            agent_type=step.run.agent_type,
            step_name=step.run.workflow_step or "m6_agent_step",
            step_purpose="保存未完成 M6 Agent 步骤的真实工具证据。",
        )
        for item in step.executor.tool_calls:
            record = repository.get(item.id)
            if record is None or record.provider_call_id is None:
                continue
            call = ProviderToolCall(
                call_id=record.provider_call_id,
                name=record.tool_name,
                arguments=record.arguments_json,
                item_type=record.provider_item_type or "function_call",
            )
            result = ProviderToolExecutionResult(
                status=record.status,
                result={
                    "tool_call_id": str(record.id),
                    "summary": record.result_summary or "工具步骤未完成。",
                    "result_json": record.result_json or {},
                    "stdout_summary": record.stdout_summary,
                    "stderr_summary": record.stderr_summary,
                    "duration_ms": record.duration_ms,
                },
                error_code=record.error_code,
            )
            turn.add(call, result, purpose="恢复已持久化工具调用。")
        if turn.call_count:
            turn.commit(
                step.conversation,
                summary=(
                    "M6 Agent 步骤未完成："
                    f"{getattr(exc, 'code', type(exc).__name__)}。"
                ),
            )

    @staticmethod
    def raise_for_infrastructure(output: BaseModel) -> None:
        """Tool CLI/timeout/manifest 等基础设施异常进入 paused，而非业务回退。"""

        tool_calls = list(getattr(output, "tool_calls", []))
        for call in tool_calls:
            if call.error_code in RECOVERABLE_SERVICE_ERROR_CODES:
                raise ServiceError(
                    call.error_code,
                    call.summary,
                    409,
                )
        blockers = [str(item) for item in getattr(output, "blockers", [])]
        failures = [
            str(item) for item in getattr(output, "failure_reasons", [])
        ]
        messages = [*blockers, *failures]
        if any(message.startswith("缺少工具：") for message in messages):
            raise ServiceError(
                "tool_manifest_incomplete",
                "M6 稳定工具清单缺少当前 Agent 所需工具。",
                409,
            )
