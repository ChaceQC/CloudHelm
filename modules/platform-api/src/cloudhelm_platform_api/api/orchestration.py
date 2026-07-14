"""M4 Orchestration API 路由。"""

from uuid import UUID

from fastapi import APIRouter, Body

from cloudhelm_platform_api.api.deps import DbSession
from cloudhelm_platform_api.schemas.orchestration import (
    OrchestrationActionRequest,
    OrchestrationStateRead,
    OrchestrationStepRead,
)
from cloudhelm_platform_api.services.orchestration_service import OrchestrationService

router = APIRouter(tags=["orchestration"])


@router.get(
    "/api/tasks/{task_id}/orchestration",
    response_model=OrchestrationStateRead,
    summary="读取 M4 编排状态",
)
def get_orchestration_state(task_id: UUID, db: DbSession) -> OrchestrationStateRead:
    """读取任务当前 M4 阶段和下一步动作。"""

    return OrchestrationService(db).get_state(task_id)


@router.post(
    "/api/tasks/{task_id}/start",
    response_model=OrchestrationStepRead,
    summary="启动 M4 编排",
)
def start_orchestration(
    task_id: UUID,
    db: DbSession,
    payload: OrchestrationActionRequest | None = Body(default=None),
) -> OrchestrationStepRead:
    """从 Created 进入 RequirementClarifying，不执行工具。"""

    payload = payload or OrchestrationActionRequest()
    return OrchestrationService(db).start(
        task_id,
        payload.actor_id,
        payload.reason,
        expected_phase=payload.expected_phase,
    )


@router.post(
    "/api/tasks/{task_id}/run-next",
    response_model=OrchestrationStepRead,
    summary="推进一个 M4 Agent 步骤",
)
def run_next_orchestration_step(
    task_id: UUID,
    db: DbSession,
    payload: OrchestrationActionRequest | None = Body(default=None),
) -> OrchestrationStepRead:
    """根据当前阶段运行 Requirement / Architect / Planner 的一个最小步骤。"""

    payload = payload or OrchestrationActionRequest()
    return OrchestrationService(db).run_next(
        task_id,
        payload.actor_id,
        payload.reason,
        expected_phase=payload.expected_phase,
    )
