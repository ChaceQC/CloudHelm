"""M4 Requirement、Architect、Planner 单步执行器。

执行器负责运行结构化 Agent、持久化对应产物并写入事件；状态机仍由
OrchestrationService 决策，事务提交仍由该入口统一完成。
"""

from cloudhelm_agent_runtime.agents import ArchitectAgent, PlannerAgent, RequirementAgent
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel as AgentRiskLevel
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput
from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentInput
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion, RequirementAgentInput, RequirementConstraint

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentOutput
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import DevelopmentPlanRepository
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.schemas.common import DevelopmentPlanStatus, ReviewStatus
from cloudhelm_platform_api.services.agent_provider_factory import AgentProviderFactory
from cloudhelm_platform_api.services.agent_run_lifecycle import AgentRunLifecycle
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class OrchestrationStepExecutor:
    """执行 M4 三类 Agent 步骤并返回新产物。"""

    def __init__(self, session, provider_factory: AgentProviderFactory, lifecycle: AgentRunLifecycle) -> None:
        self.requirements = RequirementRepository(session)
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.events = EventService(session)
        self.provider_factory = provider_factory
        self.lifecycle = lifecycle

    def run_requirement(self, task: Task) -> tuple[AgentRun, RequirementSpec]:
        """运行 Requirement Agent 并创建已校验需求规格。"""

        agent_run = self.lifecycle.start(task, "requirement")
        try:
            output = RequirementAgent(self.provider_factory.create()).run(
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
            self.lifecycle.complete(agent_run, output.summary, "requirement_agent_output", output.model_dump(mode="json"))
            self.events.record(
                "RequirementSpecCreated",
                "agent",
                str(agent_run.id),
                {"requirement_id": str(requirement.id), "task_id": str(task.id), "source": "requirement_agent"},
                task.id,
            )
            return agent_run, requirement
        except Exception as exc:
            self.lifecycle.fail(task, agent_run, exc)
            raise

    def run_architect(self, task: Task) -> tuple[AgentRun, TechnicalDesign, ArchitectAgentOutput]:
        """运行 Architect Agent 并创建技术设计。"""

        requirement = self.requirements.latest_by_task(task.id)
        if requirement is None:
            raise ServiceError("requirement_missing", "运行 Architect 前必须已有 RequirementSpec。", 409)
        agent_run = self.lifecycle.start(task, "architect")
        try:
            output = ArchitectAgent(self.provider_factory.create()).run(
                ArchitectAgentInput(
                    task_id=task.id,
                    project_id=task.project_id,
                    requirement_spec_id=requirement.id,
                    title=task.title,
                    user_story=requirement.user_story or requirement.raw_input,
                    acceptance_criteria=[AcceptanceCriterion.model_validate(item) for item in requirement.acceptance_criteria_json],
                    constraints=[RequirementConstraint.model_validate(item) for item in requirement.constraints_json],
                    task_risk_level=AgentRiskLevel(task.risk_level),
                )
            )
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
                    status=ReviewStatus.DRAFT.value if output.approval_recommended else ReviewStatus.APPROVED.value,
                    created_by_agent_run_id=agent_run.id,
                )
            )
            self.lifecycle.complete(agent_run, output.summary, "architect_agent_output", output.model_dump(mode="json"))
            self.events.record(
                "TechnicalDesignCreated",
                "agent",
                str(agent_run.id),
                {"design_id": str(design.id), "requirement_id": str(requirement.id), "risk_level": design.risk_level},
                task.id,
            )
            return agent_run, design, output
        except Exception as exc:
            self.lifecycle.fail(task, agent_run, exc)
            raise

    def run_planner(self, task: Task) -> tuple[AgentRun, DevelopmentPlan]:
        """运行 Planner Agent 并创建开发计划。"""

        design = self.designs.latest_by_task(task.id)
        if design is None:
            raise ServiceError("technical_design_missing", "运行 Planner 前必须已有 TechnicalDesign。", 409)
        if design.status != ReviewStatus.APPROVED.value:
            raise ServiceError("technical_design_not_approved", "技术设计通过后才能生成开发计划。", 409)
        agent_run = self.lifecycle.start(task, "planner")
        try:
            output = PlannerAgent(self.provider_factory.create()).run(
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
            self.lifecycle.complete(agent_run, output.summary, "planner_agent_output", output.model_dump(mode="json"))
            self.events.record(
                "DevelopmentPlanCreated",
                "agent",
                str(agent_run.id),
                {"development_plan_id": str(plan.id), "technical_design_id": str(design.id)},
                task.id,
            )
            return agent_run, plan
        except Exception as exc:
            self.lifecycle.fail(task, agent_run, exc)
            raise
