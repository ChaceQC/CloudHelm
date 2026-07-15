"""CloudHelm machine-auth HMAC 请求签名。"""

import hashlib
import hmac
import re
from collections.abc import Mapping
from uuid import UUID

from cloudhelm_remote_agent.exceptions import HeartbeatError

HEADER_TARGET_ID = "X-CloudHelm-Target-Id"
HEADER_AGENT_ID = "X-CloudHelm-Agent-Id"
HEADER_KEY_ID = "X-CloudHelm-Key-Id"
HEADER_TIMESTAMP = "X-CloudHelm-Timestamp"
HEADER_NONCE = "X-CloudHelm-Nonce"
HEADER_SIGNATURE = "X-CloudHelm-Signature"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")


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

    normalized_method = method.upper()
    fields = (normalized_method, path, timestamp, nonce, body_hash)
    if any(not field or "\n" in field or "\r" in field for field in fields):
        raise HeartbeatError(
            "machine_auth_canonical_invalid",
            "machine-auth canonical 字段无效。",
        )
    if (
        not path.startswith("/")
        or not timestamp.isdecimal()
        or not _NONCE_PATTERN.fullmatch(nonce)
    ):
        raise HeartbeatError(
            "machine_auth_canonical_invalid",
            "machine-auth canonical 字段无效。",
        )
    if not _SHA256_PATTERN.fullmatch(body_hash):
        raise HeartbeatError(
            "machine_auth_body_hash_invalid",
            "machine-auth body SHA-256 无效。",
        )
    return "\n".join(fields)


def sign_request(
    secret: bytes,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    """对实际发送的 body bytes 计算 HMAC-SHA256 lowercase hex。"""

    if not secret:
        raise HeartbeatError(
            "machine_auth_secret_empty",
            "machine-auth secret 为空。",
        )
    canonical = canonical_request(
        method,
        path,
        timestamp,
        nonce,
        body_sha256(body),
    )
    return hmac.new(
        secret,
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def authentication_headers(
    *,
    target_id: str,
    agent_id: str,
    key_id: str,
    timestamp: str,
    nonce: str,
    signature: str,
) -> Mapping[str, str]:
    """构造精确的六个 CloudHelm machine-auth header。"""

    try:
        parsed_target_id = UUID(target_id)
    except ValueError:
        parsed_target_id = None
    if (
        parsed_target_id is None
        or str(parsed_target_id) != target_id.lower()
        or not _IDENTITY_PATTERN.fullmatch(agent_id)
        or not _IDENTITY_PATTERN.fullmatch(key_id)
        or not timestamp.isdecimal()
        or not _NONCE_PATTERN.fullmatch(nonce)
        or not _SHA256_PATTERN.fullmatch(signature)
    ):
        raise HeartbeatError(
            "machine_auth_headers_invalid",
            "machine-auth 请求头格式无效。",
        )
    return {
        HEADER_TARGET_ID: target_id,
        HEADER_AGENT_ID: agent_id,
        HEADER_KEY_ID: key_id,
        HEADER_TIMESTAMP: timestamp,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: signature,
    }
