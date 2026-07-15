"""Platform API machine-auth 值对象与 canonical contract。"""

from dataclasses import dataclass
import hashlib
import re
from uuid import UUID

from cloudhelm_platform_api.services.exceptions import ServiceError

IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MachineIdentity:
    """通过 HMAC 校验且已消费 nonce 的 Remote Agent 身份。"""

    target_id: UUID
    agent_id: str
    key_id: str
    credential_id: UUID
    key_fingerprint: str


def body_sha256(body: bytes) -> str:
    """计算实际 HTTP body bytes 的 lowercase SHA-256。"""

    return hashlib.sha256(body).hexdigest()


def canonical_request(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body_hash: str,
) -> str:
    """构造无末尾换行的固定五行 canonical request。"""

    fields = (method.upper(), path, timestamp, nonce, body_hash)
    if (
        any(not item or "\r" in item or "\n" in item for item in fields)
        or not path.startswith("/")
        or not timestamp.isdecimal()
        or not SHA256_PATTERN.fullmatch(body_hash)
    ):
        raise ServiceError(
            "machine_auth_invalid",
            "Machine authentication 请求无效。",
            401,
        )
    return "\n".join(fields)
