"""M4 Agent 编排服务。

本服务是 Platform API 内的事务边界：每个编排步骤在同一事务中写入
Task 状态、AgentRun、业务产物和 EventLog。Agent Runtime 只返回已校验
结构化对象，不直接触碰数据库。
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.agents import ArchitectAgent, PlannerAgent, RequirementAgent
from cloudhelm_agent_runtime.providers import (
    AgentProviderError,
    LocalStructuredProvider,
    MissingProviderConfigurationError,
    OpenAICompatibleProvider,
    StructuredAgentProvider,
)
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel as AgentRiskLevel
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput
from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentInput
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion, RequirementAgentInput, RequirementConstraint
from cloudhelm_orchestrator.state_machine import M4Action, M4Phase, M4StateMachine, StateMachineError

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import DevelopmentPlanRepository
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.agent_run import AgentRunRead
from cloudhelm_platform_api.schemas.approval import ApprovalRequestRead
from cloudhelm_platform_api.schemas.common import AgentRunStatus, ApprovalStatus, DevelopmentPlanStatus, ReviewStatus, TaskStatus
from cloudhelm_platform_api.schemas.design import TechnicalDesignRead
from cloudhelm_platform_api.schemas.development_plan import DevelopmentPlanRead
from cloudhelm_platform_api.schemas.orchestration import OrchestrationStateRead, OrchestrationStepRead
from cloudhelm_platform_api.schemas.requirement import RequirementSpecRead
from cloudhelm_platform_api.schemas.task import TaskRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


DESIGN_APPROVAL_ACTION = "approve_technical_design"
PLAN_APPROVAL_ACTION = "approve_development_plan"


class OrchestrationService(BaseService):
    """M4 Requirement / Architect / Planner 编排服务。"""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        super().__init__(session)
        self.settings = settings or get_settings()
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.requirements = RequirementRepository(session)
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)
        self.machine = M4StateMachine()

    def start(self, task_id: UUID, actor_id: str, reason: str | None = None) -> OrchestrationStepRead:
        """从 Created 启动 M4 编排。

        已处于 M4 中间阶段时返回幂等结果；终态或 M4 外阶段返回冲突。
        """

        task = self._require_task(task_id)
        try:
            phase = self.machine.parse_phase(task.current_phase)
        except StateMachineError as exc:
            raise ServiceError("orchestration_phase_out_of_scope", str(exc), 409) from exc
        if phase == M4Phase.CREATED:
            transition = self.machine.transition(phase, M4Phase.REQUIREMENT_CLARIFYING, reason or "用户启动 M4 编排")
            self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
            task.status = TaskStatus.RUNNING.value
            self.commit()
            return self._step_result(task, "start", "已启动 M4 编排，下一步将运行 Requirement Agent。")
        if phase in {M4Phase.REQUIREMENT_CLARIFYING, M4Phase.DESIGNING, M4Phase.WAITING_DESIGN_APPROVAL, M4Phase.PLANNING}:
            return self._step_result(task, "start", "任务已处于 M4 编排阶段，start 按幂等结果返回。")
        raise ServiceError("invalid_orchestration_start", "当前阶段不允许启动 M4 编排。", 409)

    def get_state(self, task_id: UUID) -> OrchestrationStateRead:
        """读取当前 M4 编排状态摘要。"""

        task = self._require_task(task_id)
        latest_design = self.designs.latest_by_task(task.id)
        latest_plan = self.plans.latest_by_task(task.id)
        design_approved = self._is_design_approved(task, latest_design)
        try:
            next_action = self.machine.next_action(
                task.current_phase,
                design_approved=design_approved,
                plan_exists=latest_plan is not None,
            )
        except StateMachineError:
            next_action = M4Action.STOP
        return OrchestrationStateRead(
            task_id=task.id,
            current_phase=task.current_phase,
            next_action=next_action.value,
            plan_exists=latest_plan is not None,
            design_approved=design_approved,
        )

    def run_next(self, task_id: UUID, actor_id: str, reason: str | None = None) -> OrchestrationStepRead:
        """根据当前阶段推进一个最小 Agent 步骤。"""

        task = self._require_task(task_id)
        latest_design = self.designs.latest_by_task(task.id)
        latest_plan = self.plans.latest_by_task(task.id)
        design_approved = self._is_design_approved(task, latest_design)
        try:
            action = self.machine.next_action(
                task.current_phase,
                design_approved=design_approved,
                plan_exists=latest_plan is not None,
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
            approval = self.approvals.latest_by_task_and_action(task.id, DESIGN_APPROVAL_ACTION)
            return self._step_result(
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
            return self._step_result(task, action.value, "已从设计审批恢复到 Planning，可继续运行 Planner Agent。")
        if action == M4Action.RUN_PLANNER:
            return self._run_planner(task, actor_id, reason)
        return self._step_result(task, action.value, "M4 已有开发计划，无需重复生成。", development_plan=latest_plan)

    def _run_requirement(self, task: Task, actor_id: str, reason: str | None) -> OrchestrationStepRead:
        """执行 Requirement Agent 并写入需求规格。"""

        agent_run = self._create_agent_run(task, "requirement")
        try:
            provider = self._build_provider()
            output = RequirementAgent(provider).run(
                RequirementAgentInput(
                    task_id=task.id,
                    project_id=task.project_id,
                    title=task.title,
                    description=task.description,
                    source_type=task.source_type,
                    source_ref=task.source_ref,
                    risk_level=AgentRiskLevel(task.risk_level),
                )
            )
            requirement = self.requirements.create(
                RequirementSpec(
                    task_id=task.id,
                    project_id=task.project_id,
                    source_type="agent",
                    raw_input=output.raw_input,
                    user_story=output.user_story,
                    constraints_json=[item.model_dump(mode="json") for item in output.constraints],
                    acceptance_criteria_json=[item.model_dump(mode="json") for item in output.acceptance_criteria],
                    status=ReviewStatus.APPROVED.value,
                )
            )
            self._complete_agent_run(agent_run, output.summary, "requirement_agent_output", output.model_dump(mode="json"))
            self.events.record(
                "RequirementSpecCreated",
                "agent",
                str(agent_run.id),
                {"requirement_id": str(requirement.id), "task_id": str(task.id), "source": "requirement_agent"},
                task.id,
            )
            transition = self.machine.transition(
                task.current_phase,
                M4Phase.DESIGNING,
                reason or "Requirement Agent 已生成并校验需求规格。",
            )
            self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
            self.commit()
            return self._step_result(
                task,
                M4Action.RUN_REQUIREMENT.value,
                "Requirement Agent 已生成结构化需求规格。",
                agent_run=agent_run,
                requirement=requirement,
            )
        except Exception as exc:
            self._fail_agent_run(agent_run, exc)
            raise

    def _run_architect(self, task: Task, actor_id: str, reason: str | None) -> OrchestrationStepRead:
        """执行 Architect Agent 并写入技术设计。"""

        requirement = self.requirements.latest_by_task(task.id)
        if requirement is None:
            raise ServiceError("requirement_missing", "运行 Architect 前必须已有 RequirementSpec。", 409)
        agent_run = self._create_agent_run(task, "architect")
        try:
            provider = self._build_provider()
            output = ArchitectAgent(provider).run(
                ArchitectAgentInput(
                    task_id=task.id,
                    project_id=task.project_id,
                    requirement_spec_id=requirement.id,
                    title=task.title,
                    user_story=requirement.user_story or requirement.raw_input,
                    acceptance_criteria=[
                        AcceptanceCriterion.model_validate(item) for item in requirement.acceptance_criteria_json
                    ],
                    constraints=[RequirementConstraint.model_validate(item) for item in requirement.constraints_json],
                    task_risk_level=AgentRiskLevel(task.risk_level),
                )
            )
            design_status = ReviewStatus.DRAFT.value if output.approval_recommended else ReviewStatus.APPROVED.value
            design = self.designs.create(
                TechnicalDesign(
                    task_id=task.id,
                    requirement_spec_id=requirement.id,
                    design_type="m4-agent-design",
                    content_markdown=output.content_markdown,
                    openapi_json=output.openapi_json,
                    db_schema_json=output.db_schema_json,
                    mermaid_diagram=output.mermaid_diagram,
                    risk_level=output.risk_level.value,
                    status=design_status,
                    created_by_agent_run_id=agent_run.id,
                )
            )
            self._complete_agent_run(agent_run, output.summary, "architect_agent_output", output.model_dump(mode="json"))
            self.events.record(
                "TechnicalDesignCreated",
                "agent",
                str(agent_run.id),
                {"design_id": str(design.id), "requirement_id": str(requirement.id), "risk_level": design.risk_level},
                task.id,
            )
            approval = None
            if output.approval_recommended:
                approval = self._create_design_approval(task, design, agent_run, output.risks)
                target = M4Phase.WAITING_DESIGN_APPROVAL
                message = "Architect Agent 已生成高风险设计，任务进入人工设计审批。"
            else:
                target = M4Phase.PLANNING
                self.events.record(
                    "TechnicalDesignApproved",
                    "orchestrator",
                    str(agent_run.id),
                    {"design_id": str(design.id), "reason": "low risk auto approval"},
                    task.id,
                )
                message = "Architect Agent 已生成低风险设计，自动进入 Planning。"
            transition = self.machine.transition(task.current_phase, target, reason or message)
            self._apply_transition(task, transition.from_phase.value, transition.to_phase.value, transition.reason, actor_id)
            task.status = TaskStatus.WAITING_APPROVAL.value if output.approval_recommended else TaskStatus.RUNNING.value
            self.commit()
            return self._step_result(
                task,
                M4Action.RUN_ARCHITECT.value,
                message,
                agent_run=agent_run,
                technical_design=design,
                approval=approval,
            )
        except Exception as exc:
            self._fail_agent_run(agent_run, exc)
            raise

    def _run_planner(self, task: Task, actor_id: str, reason: str | None) -> OrchestrationStepRead:
        """执行 Planner Agent 并写入 DevelopmentPlan。"""

        design = self.designs.latest_by_task(task.id)
        if design is None:
            raise ServiceError("technical_design_missing", "运行 Planner 前必须已有 TechnicalDesign。", 409)
        if design.status != ReviewStatus.APPROVED.value:
            raise ServiceError("technical_design_not_approved", "技术设计通过后才能生成开发计划。", 409)
        agent_run = self._create_agent_run(task, "planner")
        try:
            provider = self._build_provider()
            output = PlannerAgent(provider).run(
                PlannerAgentInput(
                    task_id=task.id,
                    project_id=task.project_id,
                    technical_design_id=design.id,
                    title=task.title,
                    design_summary=design.content_markdown,
                    risk_level=AgentRiskLevel(design.risk_level),
                )
            )
            plan = self.plans.create(
                DevelopmentPlan(
                    task_id=task.id,
                    project_id=task.project_id,
                    technical_design_id=design.id,
                    summary=output.summary,
                    steps_json=[item.model_dump(mode="json") for item in output.steps],
                    risks_json=[item.model_dump(mode="json") for item in output.risks],
                    status=DevelopmentPlanStatus.READY_FOR_REVIEW.value,
                    created_by_agent_run_id=agent_run.id,
                )
            )
            self._complete_agent_run(agent_run, output.summary, "planner_agent_output", output.model_dump(mode="json"))
            self.events.record(
                "DevelopmentPlanCreated",
                "agent",
                str(agent_run.id),
                {"development_plan_id": str(plan.id), "technical_design_id": str(design.id)},
                task.id,
            )
            approval = self._create_plan_approval(task, plan, agent_run)
            task.status = TaskStatus.WAITING_APPROVAL.value
            task.current_phase = M4Phase.PLANNING.value
            self.events.record(
                "TaskPhaseChanged",
                "orchestrator",
                actor_id,
                {
                    "task_id": str(task.id),
                    "from": M4Phase.PLANNING.value,
                    "to": M4Phase.PLANNING.value,
                    "reason": reason or "Planner Agent 已生成开发计划，等待后续 M5 执行审批。",
                },
                task.id,
            )
            self.commit()
            return self._step_result(
                task,
                M4Action.RUN_PLANNER.value,
                "Planner Agent 已生成开发计划，M4 停在计划审查状态，不执行代码或工具。",
                agent_run=agent_run,
                development_plan=plan,
                approval=approval,
            )
        except Exception as exc:
            self._fail_agent_run(agent_run, exc)
            raise

    def _build_provider(self) -> StructuredAgentProvider:
        """根据配置创建 provider。"""

        if self.settings.agent_provider == "local_structured":
            return LocalStructuredProvider()
        if self.settings.agent_provider == "openai_compatible":
            return OpenAICompatibleProvider(
                api_base=self.settings.llm_api_base,
                api_key=self.settings.llm_api_key,
                model_name=self.settings.llm_model,
            )
        raise ServiceError("unsupported_agent_provider", f"不支持的 Agent provider：{self.settings.agent_provider}", 400)

    def _is_design_approved(self, task: Task, design: TechnicalDesign | None) -> bool:
        """同时支持 Design Review 和 Approval Panel 两条人工审批路径。"""

        if design is not None and design.status == ReviewStatus.APPROVED.value:
            return True
        approval = self.approvals.latest_by_task_and_action(task.id, DESIGN_APPROVAL_ACTION)
        return approval is not None and approval.status == ApprovalStatus.APPROVED.value

    def _create_agent_run(self, task: Task, agent_type: str) -> AgentRun:
        """创建 running AgentRun 并写入启动事件。"""

        provider_name = self.settings.agent_provider
        model_name = self.settings.llm_model if provider_name == "openai_compatible" else "local-rules-m4-v1"
        agent_run = self.agent_runs.create(
            AgentRun(
                task_id=task.id,
                agent_type=agent_type,
                status=AgentRunStatus.RUNNING.value,
                model_name=model_name,
                prompt_hash="m4-v1",
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
        )
        self.events.record(
            "AgentRunStarted",
            "orchestrator",
            agent_type,
            {"agent_run_id": str(agent_run.id), "agent_type": agent_type, "provider": provider_name},
            task.id,
        )
        return agent_run

    def _complete_agent_run(
        self,
        agent_run: AgentRun,
        summary: str,
        output_type: str,
        output_json: dict,
    ) -> None:
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

    def _fail_agent_run(self, agent_run: AgentRun, exc: Exception) -> None:
        """记录 Agent 失败、提交事件并抛出稳定业务错误。"""

        code = getattr(exc, "code", "agent_run_failed")
        message = str(exc)
        agent_run.status = AgentRunStatus.FAILED.value
        agent_run.summary = "Agent 运行失败。"
        agent_run.error_code = code
        agent_run.error_message = message
        agent_run.finished_at = utc_now()
        task = self._require_task(agent_run.task_id)
        task.status = TaskStatus.FAILED.value
        self.events.record(
            "AgentRunFailed",
            "agent",
            str(agent_run.id),
            {"agent_run_id": str(agent_run.id), "agent_type": agent_run.agent_type, "error_code": code, "message": message},
            agent_run.task_id,
        )
        self.commit()
        status_code = 409 if isinstance(exc, MissingProviderConfigurationError) else 500
        if isinstance(exc, ServiceError):
            raise ServiceError(exc.code, exc.message, exc.status_code, exc.detail) from exc
        if isinstance(exc, (AgentProviderError, MissingProviderConfigurationError)):
            raise ServiceError(code, message, status_code) from exc
        raise ServiceError("agent_output_validation_failed", message, 500) from exc

    def _create_design_approval(
        self,
        task: Task,
        design: TechnicalDesign,
        agent_run: AgentRun,
        risks: list[str],
    ) -> ApprovalRequest:
        """创建技术设计审批请求。"""

        approval = self.approvals.create(
            ApprovalRequest(
                task_id=task.id,
                action=DESIGN_APPROVAL_ACTION,
                risk_level=design.risk_level,
                reason="; ".join(risks) if risks else "Architect Agent 建议进行设计审批。",
                status=ApprovalStatus.PENDING.value,
                requested_by_agent_run_id=agent_run.id,
            )
        )
        self.events.record(
            "ApprovalRequested",
            "orchestrator",
            str(agent_run.id),
            {"approval_id": str(approval.id), "action": approval.action, "risk_level": approval.risk_level},
            task.id,
        )
        return approval

    def _create_plan_approval(self, task: Task, plan: DevelopmentPlan, agent_run: AgentRun) -> ApprovalRequest:
        """创建开发计划审查审批请求。"""

        approval = self.approvals.create(
            ApprovalRequest(
                task_id=task.id,
                action=PLAN_APPROVAL_ACTION,
                risk_level="L1",
                reason="M4 已生成开发计划；进入 M5/M6 前需要人工确认计划边界。",
                status=ApprovalStatus.PENDING.value,
                requested_by_agent_run_id=agent_run.id,
            )
        )
        self.events.record(
            "ApprovalRequested",
            "orchestrator",
            str(agent_run.id),
            {"approval_id": str(approval.id), "action": approval.action, "risk_level": approval.risk_level},
            task.id,
        )
        return approval

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

    def _step_result(
        self,
        task: Task,
        action: str,
        message: str,
        *,
        agent_run: AgentRun | None = None,
        requirement: RequirementSpec | None = None,
        technical_design: TechnicalDesign | None = None,
        development_plan: DevelopmentPlan | None = None,
        approval: ApprovalRequest | None = None,
    ) -> OrchestrationStepRead:
        """把 ORM 对象转换为 API 响应 DTO。"""

        return OrchestrationStepRead(
            task=TaskRead.model_validate(task),
            action=action,
            message=message,
            agent_run=AgentRunRead.model_validate(agent_run) if agent_run is not None else None,
            requirement=RequirementSpecRead.model_validate(requirement) if requirement is not None else None,
            technical_design=TechnicalDesignRead.model_validate(technical_design) if technical_design is not None else None,
            development_plan=DevelopmentPlanRead.model_validate(development_plan) if development_plan is not None else None,
            approval=ApprovalRequestRead.model_validate(approval) if approval is not None else None,
        )

    def _require_task(self, task_id: UUID) -> Task:
        """读取任务或抛出稳定 404。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        return task
