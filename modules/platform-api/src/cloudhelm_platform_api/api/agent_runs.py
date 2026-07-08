"""AgentRun API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.agent_run import AgentRunCreate, AgentRunRead
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.services.agent_run_service import AgentRunService

router = APIRouter(tags=["agent-runs"])


@router.post(
    "/api/tasks/{task_id}/agent-runs",
    response_model=AgentRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建 AgentRun 记录（M2 内部联调）",
)
def create_agent_run(task_id: UUID, payload: AgentRunCreate, db: DbSession) -> AgentRunRead:
    """写入 AgentRun 记录；不表示 Agent 已自动执行。"""

    return AgentRunService(db).create_agent_run(task_id, payload)


@router.get("/api/tasks/{task_id}/agent-runs", response_model=PageResponse[AgentRunRead], summary="分页读取任务 AgentRun")
def list_agent_runs(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[AgentRunRead]:
    """读取某任务下的 AgentRun 记录。"""

    limit, cursor = page
    return AgentRunService(db).list_by_task(task_id, limit, cursor)


@router.get("/api/agent-runs/{run_id}", response_model=AgentRunRead, summary="读取 AgentRun")
def get_agent_run(run_id: UUID, db: DbSession) -> AgentRunRead:
    """读取单个 AgentRun。"""

    return AgentRunService(db).get_agent_run(run_id)
