"""M6 本地开发闭环 API。"""

from uuid import UUID

from fastapi import APIRouter, Body, Request

from cloudhelm_platform_api.api.deps import DbSession
from cloudhelm_platform_api.schemas.local_development import (
    LocalDevelopmentActionRequest,
    LocalDevelopmentStateRead,
    LocalDevelopmentStepRead,
)
from cloudhelm_platform_api.services.local_development_service import (
    LocalDevelopmentService,
)

router = APIRouter(tags=["local-development"])


@router.get(
    "/api/tasks/{task_id}/local-development",
    response_model=LocalDevelopmentStateRead,
    summary="读取 M6 本地开发状态",
)
def get_local_development_state(
    task_id: UUID,
    request: Request,
    db: DbSession,
) -> LocalDevelopmentStateRead:
    """返回当前阶段、下一动作及最新 Artifact/PR 引用。"""

    return LocalDevelopmentService(
        db,
        request.app.state.tool_gateway,
    ).get_state(task_id)


@router.post(
    "/api/tasks/{task_id}/local-development/start",
    response_model=LocalDevelopmentStepRead,
    summary="启动 M6 本地开发闭环",
)
def start_local_development(
    task_id: UUID,
    request: Request,
    db: DbSession,
    payload: LocalDevelopmentActionRequest | None = Body(default=None),
) -> LocalDevelopmentStepRead:
    """校验最新版审批链，并从 Planning 进入 Scaffolding。"""

    data = payload or LocalDevelopmentActionRequest()
    return LocalDevelopmentService(
        db,
        request.app.state.tool_gateway,
    ).start(task_id, data.actor_id, data.reason)


@router.post(
    "/api/tasks/{task_id}/local-development/run-next",
    response_model=LocalDevelopmentStepRead,
    summary="推进一个 M6 本地开发步骤",
)
def run_next_local_development(
    task_id: UUID,
    request: Request,
    db: DbSession,
    payload: LocalDevelopmentActionRequest | None = Body(default=None),
) -> LocalDevelopmentStepRead:
    """执行 Scaffold、Coder、Tester、Reviewer、Security 或本地 PR 收尾。"""

    data = payload or LocalDevelopmentActionRequest()
    return LocalDevelopmentService(
        db,
        request.app.state.tool_gateway,
    ).run_next(task_id, data.actor_id, data.reason)
