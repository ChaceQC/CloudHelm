"""M4 编排审批协调服务。

审批记录必须绑定产生当前产物的 AgentRun，避免旧审批被错误复用于新设计。
"""

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.schemas.common import ApprovalStatus, ReviewStatus
from cloudhelm_platform_api.services.event_service import EventService

DESIGN_APPROVAL_ACTION = "approve_technical_design"
PLAN_APPROVAL_ACTION = "approve_development_plan"


class OrchestrationApprovalCoordinator:
    """创建编排审批并判断当前技术设计是否真正获批。"""

    def __init__(self, session) -> None:
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)

    def latest_design_approval(self, task_id):
        """读取任务最新技术设计审批。"""

        return self.approvals.latest_by_task_and_action(task_id, DESIGN_APPROVAL_ACTION)

    def is_design_approved(self, task: Task, design: TechnicalDesign | None) -> bool:
        """只接受当前设计状态或其创建 AgentRun 对应的审批。"""

        if design is None or design.status == ReviewStatus.CHANGES_REQUESTED.value:
            return False
        if design.status == ReviewStatus.APPROVED.value:
            return True
        if design.created_by_agent_run_id is None:
            return False
        approval = self.latest_design_approval(task.id)
        return (
            approval is not None
            and approval.status == ApprovalStatus.APPROVED.value
            and approval.requested_by_agent_run_id == design.created_by_agent_run_id
        )

    def create_design_approval(
        self,
        task: Task,
        design: TechnicalDesign,
        agent_run: AgentRun,
        risks: list[str],
    ) -> ApprovalRequest:
        """为当前技术设计创建人工审批。"""

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
        self._record_requested(task, approval, agent_run)
        return approval

    def create_plan_approval(
        self,
        task: Task,
        plan: DevelopmentPlan,
        agent_run: AgentRun,
    ) -> ApprovalRequest:
        """为开发计划创建进入后续里程碑前的人工审批。"""

        approval = self.approvals.create(
            ApprovalRequest(
                task_id=task.id,
                action=PLAN_APPROVAL_ACTION,
                risk_level="L1",
                reason=f"开发计划 {plan.id} 已生成；进入 M5/M6 前需要人工确认计划边界。",
                status=ApprovalStatus.PENDING.value,
                requested_by_agent_run_id=agent_run.id,
            )
        )
        self._record_requested(task, approval, agent_run)
        return approval

    def _record_requested(self, task: Task, approval: ApprovalRequest, agent_run: AgentRun) -> None:
        """写入统一 ApprovalRequested 事件。"""

        self.events.record(
            "ApprovalRequested",
            "orchestrator",
            str(agent_run.id),
            {"approval_id": str(approval.id), "action": approval.action, "risk_level": approval.risk_level},
            task.id,
        )
