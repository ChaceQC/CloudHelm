"""M7 ReleaseCandidate POST/GET API。"""

from uuid import UUID

from fastapi import APIRouter, Response, status

from cloudhelm_platform_api.api.deps import DbSession
from cloudhelm_platform_api.schemas.common import ErrorResponse
from cloudhelm_platform_api.schemas.release_candidate import (
    ReleaseCandidateCreate,
    ReleaseCandidateEnvelope,
)
from cloudhelm_platform_api.services.release_candidate_service import (
    ReleaseCandidateService,
)

router = APIRouter(tags=["release-candidates"])


@router.post(
    "/api/tasks/{task_id}/release-candidate",
    response_model=ReleaseCandidateEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="原子创建候选发布与第一道审批",
    responses={
        200: {
            "model": ReleaseCandidateEnvelope,
            "description": "同一 PR 与 Binding snapshot 的幂等命中。",
        },
        409: {
            "model": ErrorResponse,
            "description": "M6 证据、Binding 或 Candidate 状态冲突。",
        },
    },
)
def create_release_candidate(
    task_id: UUID,
    payload: ReleaseCandidateCreate,
    response: Response,
    db: DbSession,
) -> ReleaseCandidateEnvelope:
    """严格空对象请求；首次返回 201，幂等命中返回 200。"""

    del payload
    result = ReleaseCandidateService(db).create(task_id)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result.envelope


@router.get(
    "/api/tasks/{task_id}/release-candidate",
    response_model=ReleaseCandidateEnvelope,
    summary="读取任务当前或最新候选发布",
)
def get_release_candidate(
    task_id: UUID,
    db: DbSession,
) -> ReleaseCandidateEnvelope:
    """优先返回 pending/approved Candidate，否则返回最新历史。"""

    return ReleaseCandidateService(db).get(task_id)
