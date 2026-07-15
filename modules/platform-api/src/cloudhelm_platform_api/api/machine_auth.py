"""Remote Agent machine-auth FastAPI dependency。"""

from typing import Annotated

from fastapi import Depends, Request

from cloudhelm_platform_api.db.session import get_session_factory
from cloudhelm_platform_api.services.machine_auth_contract import (
    MachineIdentity,
)
from cloudhelm_platform_api.services.machine_auth_service import MachineAuthService

MACHINE_AUTH_OPENAPI_PARAMETERS: list[dict[str, object]] = [
    {
        "name": "X-CloudHelm-Target-Id",
        "in": "header",
        "required": True,
        "description": "已登记 RemoteTarget UUID。",
        "schema": {"type": "string", "format": "uuid"},
    },
    {
        "name": "X-CloudHelm-Agent-Id",
        "in": "header",
        "required": True,
        "description": "Remote Agent 稳定身份。",
        "schema": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
    },
    {
        "name": "X-CloudHelm-Key-Id",
        "in": "header",
        "required": True,
        "description": "machine credential 轮换标识。",
        "schema": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        },
    },
    {
        "name": "X-CloudHelm-Timestamp",
        "in": "header",
        "required": True,
        "description": "Unix 秒时间戳。",
        "schema": {"type": "string", "pattern": r"^\d+$"},
    },
    {
        "name": "X-CloudHelm-Nonce",
        "in": "header",
        "required": True,
        "description": "16 至 128 字符的一次性随机值。",
        "schema": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$",
        },
    },
    {
        "name": "X-CloudHelm-Signature",
        "in": "header",
        "required": True,
        "description": "lowercase hex HMAC-SHA256。",
        "schema": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
    },
]


def authenticate_remote_agent(
    request: Request,
) -> MachineIdentity:
    """在线程池中校验原始 bytes，并使用独立短 Session 消费 nonce。"""

    body = getattr(request.state, "heartbeat_body", b"")
    with get_session_factory()() as session:
        return MachineAuthService(session).authenticate(
            method=request.method,
            path=request.url.path,
            body=body,
            target_id=request.headers.get("X-CloudHelm-Target-Id"),
            agent_id=request.headers.get("X-CloudHelm-Agent-Id"),
            key_id=request.headers.get("X-CloudHelm-Key-Id"),
            timestamp=request.headers.get("X-CloudHelm-Timestamp"),
            nonce=request.headers.get("X-CloudHelm-Nonce"),
            signature=request.headers.get("X-CloudHelm-Signature"),
        )


MachineAuthIdentity = Annotated[
    MachineIdentity,
    Depends(authenticate_remote_agent),
]
