"""M6 本地代码、测试、安全与 local PR 单步编排服务。"""

from uuid import UUID

from cloudhelm_orchestrator.local_development_state_machine import (
    LocalDevelopmentAction,
    LocalDevelopmentPhase,
    LocalDevelopmentStateMachine,
    LocalDevelopmentStateMachineError,
)
from cloudhelm_tool_gateway import ToolGateway
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.schemas.common import TaskStatus
from cloudhelm_platform_api.schemas.local_development import (
    LocalDevelopmentStateRead,
    LocalDevelopmentStepRead,
)
from cloudhelm_platform_api.services.agent_run_lifecycle import AgentRunLifecycle
from cloudhelm_platform_api.services.artifact_storage import (
    discard_pending_artifacts,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContextResolver,
)
from cloudhelm_platform_api.services.local_development_action_dispatcher import (
    LocalDevelopmentActionDispatcher,
)
from cloudhelm_platform_api.services.local_development_git_service import (
    LocalDevelopmentGitService,
)
from cloudhelm_platform_api.services.local_development_response import (
    build_local_development_step,
)
from cloudhelm_platform_api.services.local_development_result import (
    LocalDevelopmentResult,
)
from cloudhelm_platform_api.services.local_development_review_security_steps import (
    LocalDevelopmentReviewSecuritySteps,
)
from cloudhelm_platform_api.services.local_development_test_step import (
    LocalDevelopmentTestStep,
)
from cloudhelm_platform_api.services.local_development_state_reader import (
    LocalDevelopmentStateReader,
)
from cloudhelm_platform_api.services.local_development_task_guard import (
    LocalDevelopmentTaskGuard,
)
from cloudhelm_platform_api.services.local_development_transition import (
    apply_task_transition,
)
from cloudhelm_platform_api.services.local_development_write_steps import (
    LocalDevelopmentWriteSteps,
)


class LocalDevelopmentService(BaseService):
    """每次请求只推进一个可审计 M6 动作。"""

    def __init__(
        self,
        session: Session,
        gateway: ToolGateway,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(session)
        self.settings = settings or get_settings()
        self.gateway = gateway
        self.contexts = LocalDevelopmentContextResolver(
            session,
            self.settings,
        )
        self.agent_runs = AgentRunRepository(session)
        self.lifecycle = AgentRunLifecycle(session, self.settings)
        self.events = EventService(session)
        self.machine = LocalDevelopmentStateMachine()
        self.state_reader = LocalDevelopmentStateReader(
            session,
            self.settings,
            self.machine,
        )
        self.guard = LocalDevelopmentTaskGuard(
            session,
            self.lifecycle,
        )
        self.write_steps = LocalDevelopmentWriteSteps(
            session,
            self.settings,
            gateway,
        )
        self.test_step = LocalDevelopmentTestStep(
            session,
            self.settings,
            gateway,
        )
        self.quality_steps = LocalDevelopmentReviewSecuritySteps(
            session,
            self.settings,
            gateway,
        )
        self.git_step = LocalDevelopmentGitService(
            session,
            self.settings,
            gateway,
        )
        self.actions = LocalDevelopmentActionDispatcher(
            self.write_steps,
            self.test_step,
            self.quality_steps,
            self.git_step,
        )

    def get_state(self, task_id: UUID) -> LocalDevelopmentStateRead:
        """读取当前阶段、下一动作、active run 与最新 evidence 引用。"""

        return self.state_reader.get(task_id)

    def start(
        self,
        task_id: UUID,
        actor_id: str,
        reason: str | None = None,
    ) -> LocalDevelopmentStepRead:
        """校验最新版审批链后只执行 Planning -> Scaffolding。"""

        task = self.guard.lock(task_id)
        self.guard.ensure_can_run(task)
        context = self.contexts.resolve(task_id)
        try:
            phase = self.machine.parse_phase(context.task.current_phase)
        except LocalDevelopmentStateMachineError as exc:
            raise ServiceError(
                "local_development_phase_out_of_scope",
                str(exc),
                409,
            ) from exc
        if phase == LocalDevelopmentPhase.PLANNING:
            transition = self.machine.transition(
                phase,
                LocalDevelopmentPhase.SCAFFOLDING,
                reason or "最新版 DevelopmentPlan 已通过，启动 M6。",
            )
            apply_task_transition(
                context.task,
                self.events,
                from_phase=transition.from_phase.value,
                to_phase=transition.to_phase.value,
                reason=transition.reason,
                actor_id=actor_id,
            )
            context.task.status = TaskStatus.RUNNING.value
            self.events.record(
                "LocalDevelopmentStarted",
                "user",
                actor_id,
                {
                    "development_plan_id": str(context.plan.id),
                    "recipe_id": context.recipe.recipe_id,
                    "recipe_sha256": context.recipe_sha256,
                },
                context.task.id,
            )
            self.commit()
            result = LocalDevelopmentResult(
                action=LocalDevelopmentAction.START.value,
                message="M6 已启动，下一步运行 Scaffold Agent。",
                target_phase=LocalDevelopmentPhase.SCAFFOLDING.value,
                gate_evidence={
                    "recipe_id": context.recipe.recipe_id,
                    "recipe_sha256": context.recipe_sha256,
                },
            )
            return build_local_development_step(context.task, result)
        if phase in set(LocalDevelopmentPhase) - {
            LocalDevelopmentPhase.PLANNING
        }:
            result = LocalDevelopmentResult(
                action=LocalDevelopmentAction.START.value,
                message="任务已处于 M6，本次 start 返回幂等状态。",
                target_phase=None,
            )
            return build_local_development_step(context.task, result)
        raise ServiceError(
            "invalid_local_development_start",
            "当前阶段不允许启动 M6。",
            409,
        )

    def run_next(
        self,
        task_id: UUID,
        actor_id: str,
        reason: str | None = None,
    ) -> LocalDevelopmentStepRead:
        """根据 M6 状态机运行一个 Agent/Git 最小步骤。"""

        task = self.guard.lock(task_id)
        self.guard.ensure_can_run(task)
        context = self.contexts.resolve(task_id)
        if self.agent_runs.list_active_by_task(task_id):
            raise ServiceError(
                "local_development_step_active",
                "当前 Task 已有 active AgentRun。",
                409,
            )
        try:
            action = self.machine.next_action(context.task.current_phase)
        except LocalDevelopmentStateMachineError as exc:
            raise ServiceError(
                "local_development_phase_out_of_scope",
                str(exc),
                409,
            ) from exc
        if action == LocalDevelopmentAction.START:
            raise ServiceError(
                "local_development_not_started",
                "请先调用 local-development/start。",
                409,
            )
        if action == LocalDevelopmentAction.STOP:
            result = LocalDevelopmentResult(
                action=action.value,
                message="M6 已创建本地等价 PR record，无需继续推进。",
                target_phase=None,
            )
            return build_local_development_step(context.task, result)

        expected_phase = context.task.current_phase
        claimed_run = self.lifecycle.start(
            context.task,
            self.actions.agent_type(action),
            workflow_step=action.value,
        )
        self.session.commit()
        try:
            result = self._dispatch(context, action)
        except Exception as exc:
            self.session.rollback()
            discard_pending_artifacts(self.session)
            self.guard.record_finalize_failure(
                task_id,
                claimed_run.id,
                exc,
            )
            raise
        try:
            task = self.guard.lock(task_id)
            self.guard.ensure_can_run(task)
            if task.current_phase != expected_phase:
                raise ServiceError(
                    "local_development_phase_changed",
                    "M6 步骤执行期间 Task 阶段已变化，拒绝提交本轮结果。",
                    409,
                )
            if (
                result.target_phase is not None
                and result.target_phase != task.current_phase
            ):
                transition = self.machine.transition(
                    task.current_phase,
                    LocalDevelopmentPhase(result.target_phase),
                    reason or result.message,
                )
                apply_task_transition(
                    task,
                    self.events,
                    from_phase=transition.from_phase.value,
                    to_phase=transition.to_phase.value,
                    reason=transition.reason,
                    actor_id=actor_id,
                )
            task.status = TaskStatus.RUNNING.value
            self.commit()
        except Exception as exc:
            self.session.rollback()
            discard_pending_artifacts(self.session)
            self.guard.record_finalize_failure(
                task_id,
                claimed_run.id,
                exc,
            )
            raise
        return build_local_development_step(task, result)

    def _dispatch(self, context, action):
        """保留可测试的单步派发边界，具体映射由独立组件维护。"""

        return self.actions.dispatch(context, action)
