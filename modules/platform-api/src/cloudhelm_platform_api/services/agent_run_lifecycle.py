"""M4 AgentRun 生命周期管理。

本模块只修改 AgentRun、Task 和 EventLog，不负责运行具体 Agent 或提交事务。
调用方在成功路径中统一提交；失败路径由本类提交可追溯的失败记录。
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from cloudhelm_agent_runtime.providers import (
    AgentProviderError,
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
    ProviderCallMetadata,
    ProviderConversation,
    UnsupportedLocalRecipeError,
)

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.schemas.common import AgentRunStatus, TaskStatus
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError

RECOVERABLE_SERVICE_ERROR_CODES = {
    "agent_conversation_revision_conflict",
    "command_not_found",
    "command_timeout",
    "database_error",
    "git_add_failed",
    "git_branch_exists",
    "git_commit_failed",
    "git_create_branch_failed",
    "git_diff_failed",
    "git_format_patch_failed",
    "git_index_check_failed",
    "git_index_not_clean",
    "git_no_staged_changes",
    "git_not_found",
    "git_ref_not_found",
    "git_status_failed",
    "git_timeout",
    "junit_parse_failed",
    "m6_junit_artifact_empty",
    "m6_junit_artifact_missing",
    "m6_junit_integrity_mismatch",
    "pytest_command_not_found",
    "pytest_execution_failed",
    "pytest_timeout",
    "security_command_not_found",
    "security_report_parse_failed",
    "security_scan_failed",
    "security_scan_timeout",
    "task_state_changed_during_tool_execution",
    "tool_execution_error",
    "tool_executor_error",
    "tool_manifest_incomplete",
}


class AgentRunLifecycle(BaseService):
    """创建、完成和失败 AgentRun，并维护对应事件。"""

    def __init__(self, session, settings: Settings) -> None:
        super().__init__(session)
        self.settings = settings
        self.agent_runs = AgentRunRepository(session)
        self.events = EventService(session)

    def start(
        self,
        task: Task,
        agent_type: str,
        *,
        workflow_step: str | None = None,
    ) -> AgentRun:
        """创建 running AgentRun 并写入启动事件。

        M6 工作流步骤使用 task/step/attempt 形成数据库幂等身份；M4 调用方
        继续省略 ``workflow_step``，保持原有 AgentRun 语义。
        """

        provider_name = self.settings.agent_provider
        model_name = (
            self.settings.llm_model
            if provider_name == "openai_compatible"
            else (
                "local-rules-m6-v2"
                if workflow_step is not None
                else "local-rules-m4-v1"
            )
        )
        prompt_hash = (
            (
                f"{'m6-v2' if workflow_step else 'm4-v3'}:"
                f"{self.settings.llm_api_mode}:{self.settings.llm_reasoning_effort}:"
                f"attempts={self.settings.llm_max_attempts}"
            )
            if provider_name == "openai_compatible"
            else ("m6-v2" if workflow_step is not None else "m4-v1")
        )
        attempt = (
            self.agent_runs.next_attempt(task.id, workflow_step)
            if workflow_step is not None
            else None
        )
        idempotency_key = (
            f"m6:{workflow_step}:{attempt}"
            if workflow_step is not None and attempt is not None
            else None
        )
        try:
            agent_run = self.agent_runs.create(
                AgentRun(
                    task_id=task.id,
                    agent_type=agent_type,
                    status=AgentRunStatus.RUNNING.value,
                    workflow_step=workflow_step,
                    attempt=attempt,
                    idempotency_key=idempotency_key,
                    model_name=model_name,
                    prompt_hash=prompt_hash,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=Decimal("0"),
                )
            )
        except IntegrityError as exc:
            self.session.rollback()
            raise ServiceError(
                "local_development_step_active",
                "当前 Task 已有 active M6 AgentRun。",
                409,
            ) from exc
        self.events.record(
            "AgentRunStarted",
            "orchestrator",
            agent_type,
            {
                "agent_run_id": str(agent_run.id),
                "agent_type": agent_type,
                "workflow_step": workflow_step,
                "attempt": attempt,
                "provider": provider_name,
                "api_mode": self.settings.llm_api_mode if provider_name == "openai_compatible" else None,
                "reasoning_effort": (
                    self.settings.llm_reasoning_effort if provider_name == "openai_compatible" else None
                ),
                "max_attempts": self.settings.llm_max_attempts if provider_name == "openai_compatible" else None,
            },
            task.id,
        )
        return agent_run

    def claim_or_start(
        self,
        task: Task,
        agent_type: str,
        *,
        workflow_step: str,
    ) -> AgentRun:
        """复用初始 Task lock 事务已抢占的 run，否则原子创建。"""

        active = self.agent_runs.active_workflow_run(
            task.id,
            workflow_step,
        )
        if active is not None:
            if active.agent_type != agent_type:
                raise ServiceError(
                    "local_development_step_claim_mismatch",
                    "Active AgentRun 与当前 M6 步骤角色不一致。",
                    409,
                )
            return active
        return self.start(
            task,
            agent_type,
            workflow_step=workflow_step,
        )

    def complete(
        self,
        agent_run: AgentRun,
        summary: str,
        output_type: str,
        output_json: dict,
        provider_metadata: ProviderCallMetadata | None = None,
        conversation: ProviderConversation | None = None,
    ) -> None:
        """标记 AgentRun 成功并写入完成事件。"""

        agent_run.status = AgentRunStatus.SUCCEEDED.value
        agent_run.summary = summary
        agent_run.structured_output_type = output_type
        agent_run.structured_output_json = output_json
        if conversation is not None:
            agent_run.conversation_id = UUID(conversation.conversation_id)
            agent_run.conversation_turn = conversation.turn_count
        if provider_metadata is not None:
            agent_run.input_tokens = provider_metadata.input_tokens
            agent_run.output_tokens = provider_metadata.output_tokens
            agent_run.cached_input_tokens = provider_metadata.cached_input_tokens
            agent_run.provider_request_count = provider_metadata.request_count
            agent_run.provider_requests = [
                usage.to_json()
                for usage in provider_metadata.request_usages
            ]
            agent_run.provider_response_id = provider_metadata.response_id
            agent_run.prompt_cache_key = provider_metadata.prompt_cache_key
        agent_run.finished_at = utc_now()
        cache_payload = (
            {
                "prompt_cache_key": provider_metadata.prompt_cache_key,
                "cached_input_tokens": provider_metadata.cached_input_tokens,
                "cache_hit": provider_metadata.cached_input_tokens > 0,
                "provider_response_id": provider_metadata.response_id,
                "provider_request_count": provider_metadata.request_count,
                "requests": [
                    usage.to_json()
                    for usage in provider_metadata.request_usages
                ],
            }
            if provider_metadata is not None
            else None
        )
        self.events.record(
            "AgentRunCompleted",
            "agent",
            str(agent_run.id),
            {
                "agent_run_id": str(agent_run.id),
                "agent_type": agent_run.agent_type,
                "summary": summary,
                "input_tokens": agent_run.input_tokens,
                "output_tokens": agent_run.output_tokens,
                "cached_input_tokens": agent_run.cached_input_tokens,
                "conversation_id": (
                    str(agent_run.conversation_id)
                    if agent_run.conversation_id
                    else None
                ),
                "conversation_turn": agent_run.conversation_turn,
                "cache": cache_payload,
            },
            agent_run.task_id,
        )

    def fail(self, task: Task, agent_run: AgentRun, exc: Exception) -> None:
        """记录失败并按可恢复性更新 Task，然后抛出稳定业务错误。"""

        code = getattr(exc, "code", "agent_run_failed")
        message = str(exc)
        agent_run.status = AgentRunStatus.FAILED.value
        agent_run.summary = "Agent 运行失败。"
        agent_run.error_code = code
        agent_run.error_message = message
        agent_run.finished_at = utc_now()
        recoverable = (
            isinstance(exc, (MissingProviderConfigurationError, UnsupportedLocalRecipeError))
            or isinstance(exc, AgentProviderResponseError)
            or (isinstance(exc, AgentProviderRequestError) and exc.retryable)
            or (
                isinstance(exc, ServiceError)
                and exc.code in RECOVERABLE_SERVICE_ERROR_CODES
            )
        )
        task.status = TaskStatus.PAUSED.value if recoverable else TaskStatus.FAILED.value
        self.events.record(
            "AgentRunFailed",
            "agent",
            str(agent_run.id),
            {
                "agent_run_id": str(agent_run.id),
                "agent_type": agent_run.agent_type,
                "error_code": code,
                "message": message,
                "recoverable": recoverable,
            },
            agent_run.task_id,
        )
        self.commit()
        if isinstance(exc, ServiceError):
            raise ServiceError(exc.code, exc.message, exc.status_code, exc.detail) from exc
        if isinstance(exc, (MissingProviderConfigurationError, UnsupportedLocalRecipeError)):
            raise ServiceError(code, message, 409) from exc
        if isinstance(exc, AgentProviderRequestError):
            raise ServiceError(code, message, 503 if exc.retryable else 502) from exc
        if isinstance(exc, AgentProviderResponseError):
            raise ServiceError(code, message, 502) from exc
        if isinstance(exc, AgentProviderError):
            raise ServiceError(code, message, 500) from exc
        raise ServiceError("agent_output_validation_failed", message, 500) from exc
