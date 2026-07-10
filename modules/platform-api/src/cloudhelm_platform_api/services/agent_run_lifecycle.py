"""M4 AgentRun 生命周期管理。

本模块只修改 AgentRun、Task 和 EventLog，不负责运行具体 Agent 或提交事务。
调用方在成功路径中统一提交；失败路径由本类提交可追溯的失败记录。
"""

from decimal import Decimal

from cloudhelm_agent_runtime.providers import (
    AgentProviderError,
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
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


class AgentRunLifecycle(BaseService):
    """创建、完成和失败 AgentRun，并维护对应事件。"""

    def __init__(self, session, settings: Settings) -> None:
        super().__init__(session)
        self.settings = settings
        self.agent_runs = AgentRunRepository(session)
        self.events = EventService(session)

    def start(self, task: Task, agent_type: str) -> AgentRun:
        """创建 running AgentRun 并写入启动事件。"""

        provider_name = self.settings.agent_provider
        model_name = self.settings.llm_model if provider_name == "openai_compatible" else "local-rules-m4-v1"
        prompt_hash = (
            (
                f"m4-v3:{self.settings.llm_api_mode}:{self.settings.llm_reasoning_effort}:"
                f"attempts={self.settings.llm_max_attempts}"
            )
            if provider_name == "openai_compatible"
            else "m4-v1"
        )
        agent_run = self.agent_runs.create(
            AgentRun(
                task_id=task.id,
                agent_type=agent_type,
                status=AgentRunStatus.RUNNING.value,
                model_name=model_name,
                prompt_hash=prompt_hash,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        )
        self.events.record(
            "AgentRunStarted",
            "orchestrator",
            agent_type,
            {
                "agent_run_id": str(agent_run.id),
                "agent_type": agent_type,
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

    def complete(self, agent_run: AgentRun, summary: str, output_type: str, output_json: dict) -> None:
        """标记 AgentRun 成功并写入完成事件。"""

        agent_run.status = AgentRunStatus.SUCCEEDED.value
        agent_run.summary = summary
        agent_run.structured_output_type = output_type
        agent_run.structured_output_json = output_json
        agent_run.finished_at = utc_now()
        self.events.record(
            "AgentRunCompleted",
            "agent",
            str(agent_run.id),
            {"agent_run_id": str(agent_run.id), "agent_type": agent_run.agent_type, "summary": summary},
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
            isinstance(exc, MissingProviderConfigurationError)
            or isinstance(exc, AgentProviderResponseError)
            or (isinstance(exc, AgentProviderRequestError) and exc.retryable)
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
        if isinstance(exc, MissingProviderConfigurationError):
            raise ServiceError(code, message, 409) from exc
        if isinstance(exc, AgentProviderRequestError):
            raise ServiceError(code, message, 503 if exc.retryable else 502) from exc
        if isinstance(exc, AgentProviderResponseError):
            raise ServiceError(code, message, 502) from exc
        if isinstance(exc, AgentProviderError):
            raise ServiceError(code, message, 500) from exc
        raise ServiceError("agent_output_validation_failed", message, 500) from exc
