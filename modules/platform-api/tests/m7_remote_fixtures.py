"""M7 Environment、RemoteTarget 与 machine-auth 测试辅助。"""

from datetime import UTC, datetime
import hashlib
import hmac
import json
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from conftest import M7_REMOTE_AGENT_SECRETS

HEARTBEAT_PATH = "/api/remote-agents/heartbeat"


def create_environment(
    client: TestClient,
    project_id: str,
    *,
    name: str = "staging",
    environment_type: str = "staging",
    base_url: str = "https://staging.example.test",
) -> dict:
    """通过真实 API 创建测试 Environment。"""

    response = client.post(
        f"/api/projects/{project_id}/environments",
        json={
            "name": name,
            "environment_type": environment_type,
            "base_url": base_url,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_remote_target(
    client: TestClient,
    environment_id: str,
    *,
    profile_key: str = "test-primary",
    display_name: str = "测试远端 Agent",
) -> dict:
    """通过受控 profile 注册测试 RemoteTarget。"""

    response = client.post(
        f"/api/environments/{environment_id}/remote-targets",
        json={
            "profile_key": profile_key,
            "display_name": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def heartbeat_body(
    target_id: str,
    *,
    agent_id: str = "remote-agent-a",
    agent_version: str = "0.1.0",
    capabilities: list[str] | None = None,
    reported_at: datetime | None = None,
) -> bytes:
    """生成签名后可原样发送的紧凑 UTF-8 heartbeat body。"""

    payload = {
        "target_id": target_id,
        "agent_id": agent_id,
        "agent_version": agent_version,
        "capabilities": capabilities or ["heartbeat"],
        "reported_at": (reported_at or datetime.now(UTC)).isoformat(),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def signed_headers(
    target_id: str,
    body: bytes,
    *,
    agent_id: str = "remote-agent-a",
    key_id: str = "key-current",
    credential_ref: str = "test/agent-a/current",
    timestamp: str | None = None,
    nonce: str | None = None,
    secret: str | None = None,
    method: str = "POST",
    path: str = HEARTBEAT_PATH,
) -> dict[str, str]:
    """独立按协议生成 machine-auth 请求头，避免复用生产签名函数。"""

    timestamp_value = timestamp or str(int(time.time()))
    nonce_value = nonce or f"nonce-{uuid4().hex}"
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (
            method.upper(),
            path,
            timestamp_value,
            nonce_value,
            body_hash,
        )
    )
    resolved_secret = secret or M7_REMOTE_AGENT_SECRETS[credential_ref]
    signature = hmac.new(
        resolved_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-CloudHelm-Target-Id": target_id,
        "X-CloudHelm-Agent-Id": agent_id,
        "X-CloudHelm-Key-Id": key_id,
        "X-CloudHelm-Timestamp": timestamp_value,
        "X-CloudHelm-Nonce": nonce_value,
        "X-CloudHelm-Signature": signature,
    }
