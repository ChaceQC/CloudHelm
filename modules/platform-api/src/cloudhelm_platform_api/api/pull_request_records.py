"""M6 本地等价 PullRequestRecord 查询 API。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordRead,
    PullRequestRecordStatus,
)
from cloudhelm_platform_api.services.pull_request_record_service import (
    PullRequestRecordService,
)

router = APIRouter(tags=["pull-request-records"])


@router.get(
    "/api/tasks/{task_id}/pull-request-records",
    response_model=PageResponse[PullRequestRecordRead],
    summary="分页读取任务本地 PR records",
)
def list_pull_request_records(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
    record_status: Annotated[
        PullRequestRecordStatus | None,
        Query(
            alias="status",
            description="按 PR record 状态过滤。",
        ),
    ] = None,
) -> PageResponse[PullRequestRecordRead]:
    """读取指定 Task 的本地 branch、commit 和门禁证据记录。"""

    limit, cursor = page
    return PullRequestRecordService(db).list_by_task(
        task_id,
        limit,
        cursor,
        status=record_status.value if record_status is not None else None,
    )


@router.get(
    "/api/pull-request-records/{record_id}",
    response_model=PullRequestRecordRead,
    summary="读取本地 PR record",
)
def get_pull_request_record(
    record_id: UUID,
    db: DbSession,
) -> PullRequestRecordRead:
    """读取单个本地等价 PR record；local provider 不返回伪造 URL。"""

    return PullRequestRecordService(db).get(record_id)
