"""Remote Agent machine-auth ingress API。"""

from fastapi import APIRouter

from cloudhelm_platform_api.api.deps import DbSession
from cloudhelm_platform_api.api.machine_auth import (
    MACHINE_AUTH_OPENAPI_PARAMETERS,
    MachineAuthIdentity,
)
from cloudhelm_platform_api.schemas.common import ErrorResponse
from cloudhelm_platform_api.schemas.remote_target import (
    RemoteAgentHeartbeat,
    RemoteAgentHeartbeatRead,
)
from cloudhelm_platform_api.services.remote_agent_heartbeat_service import (
    RemoteAgentHeartbeatService,
)

router = APIRouter(prefix="/api/remote-agents", tags=["remote-agents"])


@router.post(
    "/heartbeat",
    response_model=RemoteAgentHeartbeatRead,
    summary="接收已签名 Remote Agent heartbeat",
    responses={
        401: {
            "model": ErrorResponse,
            "description": "machine authentication 无效、失效或重放。",
        },
        403: {
            "model": ErrorResponse,
            "description": "RemoteTarget 已禁用或 credential scope 不允许。",
        },
        413: {
            "model": ErrorResponse,
            "description": "heartbeat 原始请求体超过配置上限。",
        },
        503: {
            "model": ErrorResponse,
            "description": "machine credential 服务端配置不可用或发生漂移。",
        },
    },
    openapi_extra={"parameters": MACHINE_AUTH_OPENAPI_PARAMETERS},
)
def record_remote_agent_heartbeat(
    payload: RemoteAgentHeartbeat,
    identity: MachineAuthIdentity,
    db: DbSession,
) -> RemoteAgentHeartbeatRead:
    """验证 machine identity 后更新在线状态与安全事件。"""

    return RemoteAgentHeartbeatService(db).record_heartbeat(
        identity,
        payload,
    )
