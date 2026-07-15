"""Heartbeat HTTP 请求、响应和循环恢复测试。"""

import asyncio
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from uuid import UUID

import httpx2
import pytest

from cloudhelm_remote_agent.auth import sign_request
from cloudhelm_remote_agent.exceptions import HeartbeatError
from cloudhelm_remote_agent.heartbeat import HEARTBEAT_PATH, HeartbeatClient
from conftest import TEST_TARGET_ID, make_settings

FIXED_NOW = datetime(2026, 7, 15, 0, 0, 0, tzinfo=UTC)


def _ack(
    *,
    target_id: str = str(TEST_TARGET_ID),
    agent_id: str = "agent-01",
) -> dict:
    """构造 Platform API 成功确认。"""

    return {
        "target_id": target_id,
        "agent_id": agent_id,
        "status": "online",
        "accepted_at": "2026-07-15T00:00:01Z",
        "next_heartbeat_after_seconds": 20,
    }


def test_send_once_uses_exact_signed_body_and_headers(tmp_path: Path) -> None:
    """实际发送 bytes 与签名输入一致，且响应身份通过校验。"""

    secret = b"request-test-secret-32-bytes-long"
    settings = make_settings(tmp_path, secret=secret)
    captured: dict[str, object] = {}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        body = await request.aread()
        captured.update(
            method=request.method,
            path=request.url.path,
            body=body,
            headers=dict(request.headers),
        )
        return httpx2.Response(200, json=_ack())

    client = HeartbeatClient(
        settings,
        transport=httpx2.MockTransport(handler),
        clock=lambda: FIXED_NOW,
        nonce_factory=lambda: "fixed-nonce-0001",
    )
    result = asyncio.run(client.send_once())

    expected_body = (
        b'{"agent_id":"agent-01","agent_version":"0.5.1",'
        b'"capabilities":["health","heartbeat"],'
        b'"reported_at":"2026-07-15T00:00:00Z",'
        b'"target_id":"00000000-0000-0000-0000-000000000001"}'
    )
    expected_signature = sign_request(
        secret,
        "POST",
        HEARTBEAT_PATH,
        "1784073600",
        "fixed-nonce-0001",
        expected_body,
    )
    headers = captured["headers"]
    assert captured["method"] == "POST"
    assert captured["path"] == HEARTBEAT_PATH
    assert captured["body"] == expected_body
    assert headers["x-cloudhelm-target-id"] == str(TEST_TARGET_ID)
    assert headers["x-cloudhelm-agent-id"] == "agent-01"
    assert headers["x-cloudhelm-key-id"] == "key-2026-07-a"
    assert headers["x-cloudhelm-timestamp"] == "1784073600"
    assert headers["x-cloudhelm-nonce"] == "fixed-nonce-0001"
    assert headers["x-cloudhelm-signature"] == expected_signature
    assert "x-cloudhelm-content-sha256" not in headers
    assert json.loads(expected_body) == {
        "target_id": str(TEST_TARGET_ID),
        "agent_id": "agent-01",
        "agent_version": "0.5.1",
        "capabilities": ["health", "heartbeat"],
        "reported_at": "2026-07-15T00:00:00Z",
    }
    assert result.target_id == TEST_TARGET_ID


def test_http_client_disables_environment_proxy_and_redirects(tmp_path: Path) -> None:
    """生产 client 显式设置 timeout、trust_env=False 和 follow_redirects=False。"""

    client = HeartbeatClient(make_settings(tmp_path))._create_http_client()
    try:
        assert client.trust_env is False
        assert client.follow_redirects is False
        assert client.timeout.connect == 2.0
        assert client.timeout.read == 2.0
        assert client.timeout.write == 2.0
        assert client.timeout.pool == 2.0
    finally:
        asyncio.run(client.aclose())


def test_redirect_is_not_followed(tmp_path: Path) -> None:
    """Platform API redirect 被视为失败，且不会向 Location 发送第二个请求。"""

    calls = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            307,
            headers={"Location": "https://other.example.test/heartbeat"},
        )

    client = HeartbeatClient(
        make_settings(tmp_path),
        transport=httpx2.MockTransport(handler),
        clock=lambda: FIXED_NOW,
    )
    with pytest.raises(HeartbeatError) as error:
        asyncio.run(client.send_once())

    assert error.value.code == "heartbeat_http_error"
    assert error.value.status_code == 307
    assert calls == 1


@pytest.mark.parametrize("status_code", [400, 401, 429, 503])
def test_error_response_returns_stable_error(
    tmp_path: Path,
    status_code: int,
) -> None:
    """非 200 响应不回显服务端正文，并保留状态码供审计。"""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status_code,
            text="server-secret-response-body",
        )

    client = HeartbeatClient(
        make_settings(tmp_path),
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(HeartbeatError) as error:
        asyncio.run(client.send_once())

    assert error.value.code == "heartbeat_http_error"
    assert error.value.status_code == status_code
    assert "server-secret-response-body" not in error.value.message


def test_response_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    """成功状态也必须与请求 target/agent 身份完全一致。"""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json=_ack(
                target_id="00000000-0000-0000-0000-000000000002"
            ),
        )

    client = HeartbeatClient(
        make_settings(tmp_path),
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(HeartbeatError) as error:
        asyncio.run(client.send_once())

    assert error.value.code == "heartbeat_response_identity_mismatch"


def test_oversized_response_is_rejected_before_json_parsing(
    tmp_path: Path,
) -> None:
    """ACK 正文超过 16 KiB 时返回稳定错误且不保留正文。"""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=b"{" + (b"x" * (16 * 1024)) + b"}",
        )

    client = HeartbeatClient(
        make_settings(tmp_path),
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(HeartbeatError) as error:
        asyncio.run(client.send_once())

    assert error.value.code == "heartbeat_response_too_large"


def test_invalid_json_response_has_stable_error(tmp_path: Path) -> None:
    """HTTP 200 但 ACK 不是 JSON 时不得进入 worker 状态。"""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"{bad")

    client = HeartbeatClient(
        make_settings(tmp_path),
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(HeartbeatError) as error:
        asyncio.run(client.send_once())

    assert error.value.code == "heartbeat_response_invalid"


def test_run_forever_recovers_after_failure_and_stops_cleanly(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """一次服务端失败不会终止 worker，后续成功后可由 stop event 优雅退出。"""

    calls = 0
    stop_event = asyncio.Event()
    secret_text = "loop-sensitive-secret"
    settings = make_settings(
        tmp_path,
        secret=secret_text.encode("utf-8"),
        heartbeat_seconds=0.1,
    )

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx2.Response(503, text=f"response-{secret_text}")
        stop_event.set()
        return httpx2.Response(200, json=_ack())

    client = HeartbeatClient(
        settings,
        transport=httpx2.MockTransport(handler),
        clock=lambda: FIXED_NOW,
    )
    with caplog.at_level(logging.WARNING):
        asyncio.run(client.run_forever(stop_event))

    assert calls == 2
    assert "heartbeat_http_error" in caplog.text
    assert secret_text not in caplog.text
    assert str(settings.credential_file) not in caplog.text


def test_pre_set_stop_event_sends_no_request(tmp_path: Path) -> None:
    """停止请求在 worker 启动前到达时不产生网络副作用。"""

    calls = 0
    stop_event = asyncio.Event()
    stop_event.set()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=_ack())

    client = HeartbeatClient(
        make_settings(tmp_path),
        transport=httpx2.MockTransport(handler),
    )
    asyncio.run(client.run_forever(stop_event))

    assert calls == 0
