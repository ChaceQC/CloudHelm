"""M4 编排 API 响应组装。"""

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.schemas.agent_run import AgentRunRead
from cloudhelm_platform_api.schemas.approval import ApprovalRequestRead
from cloudhelm_platform_api.schemas.design import TechnicalDesignRead
from cloudhelm_platform_api.schemas.development_plan import DevelopmentPlanRead
from cloudhelm_platform_api.schemas.orchestration import OrchestrationStepRead
from cloudhelm_platform_api.schemas.requirement import RequirementSpecRead
from cloudhelm_platform_api.schemas.task import TaskRead


def build_orchestration_step(
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
    """把编排事务中的 ORM 对象转换为稳定响应 DTO。"""

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
