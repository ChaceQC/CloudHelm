"""M4 Agent 编排服务。

本服务是 Platform API 内的事务边界：每个编排步骤在同一事务中写入
Task 状态、AgentRun、业务产物和 EventLog。Agent Runtime 只返回已校验
结构化对象，不直接触碰数据库。
"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_orchestrator.state_machine import M4Action, M4Phase, M4StateMachine, StateMachineError

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import DevelopmentPlanRepository
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import DevelopmentPlanStatus, ReviewStatus, TaskStatus
from cloudhelm_platform_api.schemas.orchestration import OrchestrationStateRead, OrchestrationStepRead
from cloudhelm_platform_api.services.agent_provider_factory import AgentProviderFactory
from cloudhelm_platform_api.services.agent_run_lifecycle import AgentRunLifecycle
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.orchestration_approval_service import OrchestrationApprovalCoordinator
from cloudhelm_platform_api.services.orchestration_phase_guard import ensure_expected_phase
from cloudhelm_platform_api.services.orchestration_response import build_orchestration_step
from cloudhelm_platform_api.services.orchestration_step_executor import OrchestrationStepExecutor


class OrchestrationService(BaseService):
    """M4 Requirement / Architect / Planner 编排服务。"""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        super().__init__(session)
        self.settings = settings or get_settings()
        self.tasks = TaskRepository(session)
        self.requirements = RequirementRepository(session)
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.events = EventService(session)
        self.machine = M4StateMachine()
        self.provider_factory = AgentProviderFactory(self.settings)
        self.agent_lifecycle = AgentRunLifecycle(session, self.settings)
        self.approval_coordinator = OrchestrationApprovalCoordinator(session)
        self.step_executor = OrchestrationStepExecutor(session, self.provider_factory, self.agent_lifecycle)

    def start(
        self,
        task_id: UUID,
        actor_id: str,
        reason: str | None = None,
        *,
        expected_phase: str | None = None,
    ) -> OrchestrationStepRead:
        """从 Created 启动 M4 编排。

        Task 行锁保证同一任务的启动与单步推进串行化；调用方提供
        ``expected_phase`` 时，阶段已变化的重复请求会返回稳定冲突。
        """

        task = self._require_task(task_id, for_update=True)
        ensure_expected_phase(task, expected_phase)
        self._ensure_orchestration_allowed(task)
        try:
            phase = self.machine.parse_phase(task.current_phase)
        except StateMachineError as exc:
            raise ServiceError("orchestration_phase_out_of_scope", str(exc), 409) from exc
        if phase == M4Phase.CREATED:
            transition = self.machine.transition(phase, M4Phase.REQUIREMENT_CLARIFYING, reason or "用户启动 M4 编排")
            self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
            task.status = TaskStatus.RUNNING.value
            self.commit()
            return build_orchestration_step(task, "start", "已启动 M4 编排，下一步将运行 Requirement Agent。")
        if phase in {M4Phase.REQUIREMENT_CLARIFYING, M4Phase.DESIGNING, M4Phase.WAITING_DESIGN_APPROVAL, M4Phase.PLANNING}:
            return build_orchestration_step(task, "start", "任务已处于 M4 编排阶段，start 按幂等结果返回。")
        raise ServiceError("invalid_orchestration_start", "当前阶段不允许启动 M4 编排。", 409)

    def get_state(self, task_id: UUID) -> OrchestrationStateRead:
        """读取当前 M4 编排状态摘要。"""

        task = self._require_task(task_id)
        latest_design = self.designs.latest_by_task(task.id)
        latest_plan = self.plans.latest_by_task(task.id)
        current_plan = self._current_plan(latest_design, latest_plan)
        design_approved = self.approval_coordinator.is_design_approved(task, latest_design)
        try:
            next_action = self.machine.next_action(
                task.current_phase,
                design_approved=design_approved,
                plan_exists=current_plan is not None,
            )
        except StateMachineError:
            next_action = M4Action.STOP
        return OrchestrationStateRead(
            task_id=task.id,
            current_phase=task.current_phase,
            next_action=next_action.value,
            plan_exists=current_plan is not None,
            design_approved=design_approved,
        )

    def run_next(
        self,
        task_id: UUID,
        actor_id: str,
        reason: str | None = None,
        *,
        expected_phase: str | None = None,
    ) -> OrchestrationStepRead:
        """在 Task 行锁和阶段前置条件下推进一个最小 Agent 步骤。"""

        task = self._require_task(task_id, for_update=True)
        ensure_expected_phase(task, expected_phase)
        self._ensure_orchestration_allowed(task)
        latest_design = self.designs.latest_by_task(task.id)
        latest_plan = self.plans.latest_by_task(task.id)
        current_plan = self._current_plan(latest_design, latest_plan)
        design_approved = self.approval_coordinator.is_design_approved(task, latest_design)
        try:
            action = self.machine.next_action(
                task.current_phase,
                design_approved=design_approved,
                plan_exists=current_plan is not None,
            )
        except StateMachineError as exc:
            raise ServiceError("orchestration_phase_out_of_scope", str(exc), 409) from exc

        if action == M4Action.START:
            raise ServiceError("orchestration_not_started", "请先调用 start 启动 M4 编排。", 409)
        if action == M4Action.RUN_REQUIREMENT:
            return self._run_requirement(task, actor_id, reason)
        if action == M4Action.RUN_ARCHITECT:
            return self._run_architect(task, actor_id, reason)
        if action == M4Action.WAIT_FOR_DESIGN_APPROVAL:
            approval = self.approval_coordinator.latest_design_approval(task.id)
            return build_orchestration_step(
                task,
                action.value,
                "技术设计等待人工审批，通过设计或审批后可继续推进 Planning。",
                approval=approval,
            )
        if action == M4Action.RESUME_PLANNING:
            if latest_design is not None and latest_design.status != ReviewStatus.APPROVED.value:
                latest_design.status = ReviewStatus.APPROVED.value
                self.events.record(
                    "TechnicalDesignApproved",
                    "orchestrator",
                    actor_id,
                    {"design_id": str(latest_design.id), "reason": "approval request approved"},
                    task.id,
                )
            transition = self.machine.transition(
                task.current_phase,
                M4Phase.PLANNING,
                reason or "技术设计已通过，恢复到 Planning。",
            )
            self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
            task.status = TaskStatus.RUNNING.value
            self.commit()
            return build_orchestration_step(task, action.value, "已从设计审批恢复到 Planning，可继续运行 Planner Agent。")
        if action == M4Action.RUN_PLANNER:
            return self._run_planner(task, actor_id, reason)
        return build_orchestration_step(task, action.value, "M4 已有当前设计对应的开发计划，无需重复生成。", development_plan=current_plan)

    def _run_requirement(self, task: Task, actor_id: str, reason: str | None) -> OrchestrationStepRead:
        """执行 Requirement Agent 并推进到 Designing。"""

        agent_run, requirement = self.step_executor.run_requirement(task)
        transition = self.machine.transition(
            task.current_phase,
            M4Phase.DESIGNING,
            reason or "Requirement Agent 已生成并校验需求规格。",
        )
        self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
        self.commit()
        return build_orchestration_step(
            task,
            M4Action.RUN_REQUIREMENT.value,
            "Requirement Agent 已生成结构化需求规格。",
            agent_run=agent_run,
            requirement=requirement,
        )

    def _run_architect(self, task: Task, actor_id: str, reason: str | None) -> OrchestrationStepRead:
        """执行 Architect Agent，创建审批或进入 Planning。"""

        agent_run, design, output = self.step_executor.run_architect(task)
        approval = None
        if output.requires_approval:
            approval = self.approval_coordinator.create_design_approval(task, design, agent_run, output.risks)
            target = M4Phase.WAITING_DESIGN_APPROVAL
            message = "Architect Agent 已生成高风险设计，任务进入人工设计审批。"
            task.status = TaskStatus.WAITING_APPROVAL.value
        else:
            target = M4Phase.PLANNING
            message = "Architect Agent 已生成低风险设计，自动进入 Planning。"
            task.status = TaskStatus.RUNNING.value
            self.events.record(
                "TechnicalDesignApproved",
                "orchestrator",
                str(agent_run.id),
                {"design_id": str(design.id), "reason": "low risk auto approval"},
                task.id,
            )
        transition = self.machine.transition(task.current_phase, target, reason or message)
        self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
        self.commit()
        return build_orchestration_step(
            task,
            M4Action.RUN_ARCHITECT.value,
            message,
            agent_run=agent_run,
            technical_design=design,
            approval=approval,
        )

    def _run_planner(self, task: Task, actor_id: str, reason: str | None) -> OrchestrationStepRead:
        """执行 Planner Agent 并停在计划审查状态。"""

        agent_run, plan, output = self.step_executor.run_planner(task)
        approval = self.approval_coordinator.create_plan_approval(
            task,
            plan,
            agent_run,
            risk_level=output.risk_level.value,
        )
        task.status = TaskStatus.WAITING_APPROVAL.value
        self.events.record(
            "TaskPhaseChanged",
            "orchestrator",
            actor_id,
            {
                "task_id": str(task.id),
                "from": M4Phase.PLANNING.value,
                "to": M4Phase.PLANNING.value,
                "reason": reason or "Planner Agent 已生成开发计划，等待人工计划审批；批准后进入 M6 本地开发闭环。",
            },
            task.id,
        )
        self.commit()
        return build_orchestration_step(
            task,
            M4Action.RUN_PLANNER.value,
            "Planner Agent 已生成开发计划，M4 停在计划审查状态，不执行代码或工具。",
            agent_run=agent_run,
            development_plan=plan,
            approval=approval,
        )

    def _apply_transition(self, task: Task, from_phase: str, to_phase: str, reason: str, actor_id: str) -> None:
        """更新任务阶段并写入 TaskPhaseChanged。"""

        task.current_phase = to_phase
        self.events.record(
            "TaskPhaseChanged",
            "orchestrator",
            actor_id,
            {"task_id": str(task.id), "from": from_phase, "to": to_phase, "reason": reason},
            task.id,
        )

    def _require_task(
        self,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> Task:
        """读取任务或抛出稳定 404，可在写入入口抢占 Task 行锁。"""

        task = self.tasks.get(task_id, for_update=for_update)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        return task

    def _ensure_orchestration_allowed(self, task: Task) -> None:
        """暂停或终态任务不得绕过 Task API 继续推进编排。"""

        if task.status == TaskStatus.PAUSED.value:
            raise ServiceError("task_paused", "任务已暂停，请先恢复后再推进编排。", 409)
        if task.status in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
            raise ServiceError("task_terminal", "终态任务不能继续推进编排。", 409)

    def _current_plan(self, design, plan):
        """只把当前设计对应且未被要求修改的计划视为有效。"""

        if design is None or plan is None:
            return None
        if design.status != ReviewStatus.APPROVED.value:
            return None
        if plan.technical_design_id != design.id:
            return None
        if plan.status == DevelopmentPlanStatus.CHANGES_REQUESTED.value:
            return None
        return plan
