"""Task-facing commands keep model execution in the existing worker queue."""

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p2.task_agent import (
    StartTaskAgentRequest, TaskAgentCommandResult, TaskAgentDiff, TaskAgentRunDetail, TaskAgentSummary,
)
from .auth import get_runtime
from .contracts import ApiErrorResponse
from .requests import strict_body
from .routes_tasks import ControlActor, IdempotencyKey, NormalActor

router = APIRouter(prefix="/api/tasks", tags=["task-agent"])


@router.post("/{task_id}/agent-runs", response_model=TaskAgentCommandResult, status_code=202,
             responses={code: {"model": TaskAgentCommandResult | ApiErrorResponse} for code in (403, 404, 409, 422)})
def start_agent(request: Request, task_id: Identifier, actor: NormalActor, idempotency_key: IdempotencyKey,
                body: StartTaskAgentRequest = Depends(strict_body(StartTaskAgentRequest))):
    status, result = get_runtime(request).agents.start(actor, task_id, body, idempotency_key=idempotency_key)
    return JSONResponse(status_code=status, content=result.model_dump(mode="json"))


@router.get("/{task_id}/agent-summary", response_model=TaskAgentSummary)
def query_agent_summary(request: Request, task_id: Identifier, actor: ControlActor):
    return get_runtime(request).agents.summary(actor, task_id)


@router.get("/{task_id}/agent-runs/{run_id}", response_model=TaskAgentRunDetail)
def query_agent_run(request: Request, task_id: Identifier, run_id: Identifier, actor: ControlActor):
    return get_runtime(request).agents.run_detail(actor, task_id, run_id)


@router.get("/{task_id}/agent-diff/{work_item_id}", response_model=TaskAgentDiff)
def query_diff(request: Request, task_id: Identifier, work_item_id: Identifier, actor: ControlActor):
    return get_runtime(request).agents.diff(actor, task_id, work_item_id)
