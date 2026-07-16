"""M7 machine-auth、replay 与 Remote Agent heartbeat 测试。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from threading import Barrier, Event
import time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import httpx2 as httpx
from pydantic import SecretStr, ValidationError
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from conftest import create_project
from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.remote_target import (
    RemoteAgentReplayNonce,
    RemoteTarget,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.machine_auth_service import (
    MachineAuthService,
)
from m7_remote_fixtures import (
    HEARTBEAT_PATH,
    create_environment,
    create_remote_target,
    heartbeat_body,
    signed_headers,
)


def _seed_primary_target(client: TestClient) -> tuple[dict, dict, dict]:
    """创建 Project、Environment 和 primary RemoteTarget。"""

    project = create_project(client)
    environment = create_environment(client, project["id"])
    target = create_remote_target(client, environment["id"])
    return project, environment, target


def _post_heartbeat(
    client: TestClient,
    body: bytes,
    headers: dict[str, str],
):
    """原样发送已签名 heartbeat bytes。"""

    return client.request(
        "POST",
        HEARTBEAT_PATH,
        content=body,
        headers=headers,
    )


def _event_types() -> list[str]:
    """按写入顺序读取当前测试的 M7 Remote Agent 事件。"""

    with Session(get_engine()) as session:
        return list(
            session.scalars(
                select(EventLog.event_type)
                .where(
                    EventLog.event_type.in_(
                        (
                            "RemoteAgentOnline",
                            "RemoteAgentHeartbeat",
                            "RemoteAgentOffline",
                            "RemoteAgentRecovered",
                        )
                    )
                )
                .order_by(EventLog.created_at, EventLog.id)
            )
        )


def test_valid_heartbeat_consumes_nonce_and_accepts_overlapping_keys(
    client: TestClient,
) -> None:
    """合法原始 bytes 可解析，且新旧 active key 在轮换窗口内都可用。"""

    _, _, target = _seed_primary_target(client)
    body = heartbeat_body(target["id"])
    current_headers = signed_headers(target["id"], body)

    accepted = _post_heartbeat(client, body, current_headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["target_id"] == target["id"]
    assert accepted.json()["agent_id"] == "remote-agent-a"
    assert accepted.json()["status"] == "online"
    assert accepted.json()["next_heartbeat_after_seconds"] == 20

    previous_body = heartbeat_body(target["id"])
    previous_headers = signed_headers(
        target["id"],
        previous_body,
        key_id="key-previous",
        credential_ref="test/agent-a/previous",
    )
    previous_accepted = _post_heartbeat(
        client,
        previous_body,
        previous_headers,
    )
    assert previous_accepted.status_code == 200, previous_accepted.text

    replay = _post_heartbeat(client, body, current_headers)
    assert replay.status_code == 401
    assert replay.json()["code"] == "machine_auth_replay"
    assert replay.json()["trace_id"]

    with Session(get_engine()) as session:
        stored = session.get(RemoteTarget, UUID(target["id"]))
        assert stored is not None
        nonce_count = session.scalar(
            select(func.count()).select_from(RemoteAgentReplayNonce)
        )

    assert stored.status == "online"
    assert stored.agent_version == "0.1.0"
    assert stored.capabilities_json == ["heartbeat"]
    assert nonce_count == 2
    assert _event_types() == ["RemoteAgentOnline"]


def test_machine_auth_rejects_invalid_lifecycle_scope_and_cross_target(
    client: TestClient,
) -> None:
    """认证错误码覆盖缺失、签名、时间、撤销、scope、禁用和跨 target。"""

    _, environment, target = _seed_primary_target(client)
    secondary = create_remote_target(
        client,
        environment["id"],
        profile_key="test-secondary",
        display_name="Secondary Agent",
    )
    body = heartbeat_body(target["id"])

    missing = _post_heartbeat(
        client,
        body,
        {"Content-Type": "application/json"},
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "machine_auth_required"

    wrong_signature_headers = signed_headers(
        target["id"],
        body,
        secret="wrong-secret-that-is-long-enough-00000000000000000000",
    )
    wrong_signature = _post_heartbeat(
        client,
        body,
        wrong_signature_headers,
    )
    assert wrong_signature.status_code == 401
    assert wrong_signature.json()["code"] == "machine_auth_invalid"

    expired_timestamp = str(int(time.time()) - 301)
    expired_time = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            timestamp=expired_timestamp,
        ),
    )
    assert expired_time.status_code == 401
    assert expired_time.json()["code"] == "machine_auth_expired"

    extreme_timestamp = "253402300800"
    invalid_extreme_time = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            timestamp=extreme_timestamp,
        ),
    )
    assert invalid_extreme_time.status_code == 401
    assert invalid_extreme_time.json()["code"] == "machine_auth_invalid"

    revoked = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            key_id="key-revoked",
            credential_ref="test/agent-a/revoked",
        ),
    )
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "machine_auth_revoked"

    expired_key = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            key_id="key-expired",
            credential_ref="test/agent-a/expired",
        ),
    )
    assert expired_key.status_code == 401
    assert expired_key.json()["code"] == "machine_auth_expired"

    scope_denied = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            key_id="key-deployment",
            credential_ref="test/agent-a/deployment",
        ),
    )
    assert scope_denied.status_code == 403
    assert scope_denied.json()["code"] == "machine_auth_scope_denied"

    for key_id, credential_ref in (
        ("key-revoked", "test/agent-a/revoked"),
        ("key-deployment", "test/agent-a/deployment"),
    ):
        invalid_lifecycle_signature = _post_heartbeat(
            client,
            body,
            signed_headers(
                target["id"],
                body,
                key_id=key_id,
                credential_ref=credential_ref,
                secret=(
                    "wrong-secret-that-is-long-enough-"
                    "00000000000000000000"
                ),
            ),
        )
        assert invalid_lifecycle_signature.status_code == 401
        assert invalid_lifecycle_signature.json()["code"] == (
            "machine_auth_invalid"
        )

    cross_target_body = heartbeat_body(
        secondary["id"],
        agent_id="remote-agent-a",
    )
    cross_target = _post_heartbeat(
        client,
        cross_target_body,
        signed_headers(
            secondary["id"],
            cross_target_body,
            agent_id="remote-agent-a",
            key_id="key-current",
            credential_ref="test/agent-a/current",
        ),
    )
    assert cross_target.status_code == 401
    assert cross_target.json()["code"] == "machine_auth_invalid"

    with Session(get_engine()) as session:
        stored = session.get(RemoteTarget, UUID(target["id"]))
        assert stored is not None
        stored.status = "disabled"
        session.commit()

    disabled = _post_heartbeat(
        client,
        body,
        signed_headers(target["id"], body),
    )
    assert disabled.status_code == 403
    assert disabled.json()["code"] == "remote_target_disabled"

    disabled_wrong_signature = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            secret=(
                "wrong-secret-that-is-long-enough-"
                "00000000000000000000"
            ),
        ),
    )
    assert disabled_wrong_signature.status_code == 401
    assert disabled_wrong_signature.json()["code"] == "machine_auth_invalid"

    with Session(get_engine()) as session:
        nonce_count = session.scalar(
            select(func.count()).select_from(RemoteAgentReplayNonce)
        )
    assert nonce_count == 0


def test_authenticated_invalid_body_and_target_mismatch_still_consume_nonce(
    client: TestClient,
) -> None:
    """dependency 先消费认证 nonce，随后 DTO/身份校验失败也不得重放。"""

    _, _, target = _seed_primary_target(client)
    invalid_json = b"{bad"
    invalid_json_headers = signed_headers(target["id"], invalid_json)
    for _ in range(2):
        invalid_syntax = _post_heartbeat(
            client,
            invalid_json,
            invalid_json_headers,
        )
        assert invalid_syntax.status_code == 422
        assert invalid_syntax.json()["code"] == "validation_error"

    malformed_body = json.dumps(
        {
            "target_id": target["id"],
            "agent_id": "remote-agent-a",
            "agent_version": "0.1.0",
            "reported_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    malformed_headers = signed_headers(target["id"], malformed_body)

    malformed = _post_heartbeat(
        client,
        malformed_body,
        malformed_headers,
    )
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "validation_error"

    malformed_replay = _post_heartbeat(
        client,
        malformed_body,
        malformed_headers,
    )
    assert malformed_replay.status_code == 401
    assert malformed_replay.json()["code"] == "machine_auth_replay"

    mismatch_body = heartbeat_body(str(uuid4()))
    mismatch_headers = signed_headers(target["id"], mismatch_body)
    mismatch = _post_heartbeat(client, mismatch_body, mismatch_headers)
    assert mismatch.status_code == 401
    assert mismatch.json()["code"] == "machine_auth_target_mismatch"

    mismatch_replay = _post_heartbeat(
        client,
        mismatch_body,
        mismatch_headers,
    )
    assert mismatch_replay.status_code == 401
    assert mismatch_replay.json()["code"] == "machine_auth_replay"

    stale_report_body = heartbeat_body(
        target["id"],
        reported_at=datetime.now(UTC) - timedelta(seconds=301),
    )
    stale_report_headers = signed_headers(target["id"], stale_report_body)
    stale_report = _post_heartbeat(
        client,
        stale_report_body,
        stale_report_headers,
    )
    assert stale_report.status_code == 422
    assert stale_report.json()["code"] == "heartbeat_reported_at_invalid"

    stale_report_replay = _post_heartbeat(
        client,
        stale_report_body,
        stale_report_headers,
    )
    assert stale_report_replay.status_code == 401
    assert stale_report_replay.json()["code"] == "machine_auth_replay"

    with Session(get_engine()) as session:
        nonce_count = session.scalar(
            select(func.count()).select_from(RemoteAgentReplayNonce)
        )
    assert nonce_count == 3


def test_concurrent_replay_is_decided_by_postgresql_unique_constraint(
    client: TestClient,
) -> None:
    """两个并发相同 nonce 只能有一个成功，另一请求返回稳定 replay。"""

    _, _, target = _seed_primary_target(client)
    body = heartbeat_body(target["id"])
    headers = signed_headers(target["id"], body)
    barrier = Barrier(2)

    def send_once() -> tuple[int, str]:
        with TestClient(
            create_app(),
            raise_server_exceptions=False,
        ) as concurrent_client:
            barrier.wait(timeout=10)
            response = _post_heartbeat(concurrent_client, body, headers)
            return response.status_code, response.json().get("code", "ok")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send_once(), range(2)))

    assert sorted(status for status, _ in results) == [200, 401]
    assert sorted(code for _, code in results) == [
        "machine_auth_replay",
        "ok",
    ]

    with Session(get_engine()) as session:
        nonce_count = session.scalar(
            select(func.count()).select_from(RemoteAgentReplayNonce)
        )
    assert nonce_count == 1
    assert _event_types() == ["RemoteAgentOnline"]


def test_heartbeat_event_throttle_offline_reconciliation_and_recovery(
    client: TestClient,
) -> None:
    """首次上线、降频、离线、恢复和详情变化事件形成完整闭环。"""

    _, environment, target = _seed_primary_target(client)
    first_body = heartbeat_body(target["id"])
    first = _post_heartbeat(
        client,
        first_body,
        signed_headers(target["id"], first_body),
    )
    assert first.status_code == 200
    assert _event_types() == ["RemoteAgentOnline"]

    throttled_body = heartbeat_body(target["id"])
    throttled = _post_heartbeat(
        client,
        throttled_body,
        signed_headers(target["id"], throttled_body),
    )
    assert throttled.status_code == 200
    assert _event_types() == ["RemoteAgentOnline"]

    with Session(get_engine()) as session:
        stored = session.get(RemoteTarget, UUID(target["id"]))
        assert stored is not None
        stored.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=61)
        session.commit()

    reconciled = client.get(
        f"/api/environments/{environment['id']}/remote-targets"
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["items"][0]["status"] == "offline"
    assert reconciled.json()["items"][0]["last_error_code"] == (
        "heartbeat_timeout"
    )
    assert _event_types() == [
        "RemoteAgentOnline",
        "RemoteAgentOffline",
    ]

    recovered_body = heartbeat_body(target["id"])
    recovered = _post_heartbeat(
        client,
        recovered_body,
        signed_headers(target["id"], recovered_body),
    )
    assert recovered.status_code == 200
    assert _event_types() == [
        "RemoteAgentOnline",
        "RemoteAgentOffline",
        "RemoteAgentRecovered",
    ]

    changed_body = heartbeat_body(
        target["id"],
        agent_version="0.1.1",
        capabilities=["heartbeat", "version"],
    )
    changed = _post_heartbeat(
        client,
        changed_body,
        signed_headers(target["id"], changed_body),
    )
    assert changed.status_code == 200
    assert _event_types() == [
        "RemoteAgentOnline",
        "RemoteAgentOffline",
        "RemoteAgentRecovered",
        "RemoteAgentHeartbeat",
    ]

    final_body = heartbeat_body(
        target["id"],
        agent_version="0.1.1",
        capabilities=["version", "heartbeat"],
    )
    final = _post_heartbeat(
        client,
        final_body,
        signed_headers(target["id"], final_body),
    )
    assert final.status_code == 200
    assert _event_types() == [
        "RemoteAgentOnline",
        "RemoteAgentOffline",
        "RemoteAgentRecovered",
        "RemoteAgentHeartbeat",
    ]

    with Session(get_engine()) as session:
        stored = session.get(RemoteTarget, UUID(target["id"]))
        assert stored is not None
        payloads = list(
            session.scalars(
                select(EventLog.payload)
                .where(
                    EventLog.event_type.in_(
                        (
                            "RemoteAgentOnline",
                            "RemoteAgentHeartbeat",
                            "RemoteAgentOffline",
                            "RemoteAgentRecovered",
                        )
                    )
                )
                .order_by(EventLog.created_at, EventLog.id)
            )
        )

    assert stored.status == "online"
    assert stored.last_error_code is None
    assert stored.agent_version == "0.1.1"
    assert stored.capabilities_json == ["heartbeat", "version"]
    assert all("credential" not in str(payload).lower() for payload in payloads)
    assert all("endpoint" not in str(payload).lower() for payload in payloads)


def test_heartbeat_body_limit_rejects_declared_and_chunked_oversize(
    client: TestClient,
) -> None:
    """未认证超大 body 在 JSON 解析前按实际 bytes 返回统一 413。"""

    declared = client.post(
        HEARTBEAT_PATH,
        content=b"x" * 16385,
        headers={
            "Content-Type": "application/json",
            "X-Trace-Id": "m7-body-limit-declared",
        },
    )
    assert declared.status_code == 413
    assert declared.json()["code"] == "request_body_too_large"
    assert declared.json()["detail"]["max_body_bytes"] == 16384
    assert declared.json()["trace_id"] == "m7-body-limit-declared"
    assert declared.headers["X-Trace-Id"] == "m7-body-limit-declared"

    async def send_chunked() -> httpx.Response:
        async def chunks():
            yield b"x" * 9000
            yield b"y" * 9000

        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://platform.test",
        ) as async_client:
            return await async_client.post(
                HEARTBEAT_PATH,
                content=chunks(),
                headers={"Content-Type": "application/json"},
            )

    chunked = asyncio.run(send_chunked())
    assert chunked.status_code == 413
    assert chunked.json()["code"] == "request_body_too_large"
    assert chunked.json()["trace_id"]


def test_machine_credential_fingerprint_drift_is_blocked(
    client: TestClient,
    monkeypatch,
) -> None:
    """同一 credential_ref 原地换 secret 不得绕过登记 fingerprint。"""

    _, _, target = _seed_primary_target(client)
    body = heartbeat_body(target["id"])
    replacement_secret = (
        "replacement-machine-secret-000000000000000000000000"
    )
    settings = get_settings()
    monkeypatch.setitem(
        settings.remote_agent_credentials,
        "test/agent-a/current",
        SecretStr(replacement_secret),
    )

    drifted = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            secret=replacement_secret,
        ),
    )
    assert drifted.status_code == 503
    assert drifted.json()["code"] == (
        "remote_agent_credential_fingerprint_mismatch"
    )

    stale_signer = _post_heartbeat(
        client,
        body,
        signed_headers(target["id"], body),
    )
    assert stale_signer.status_code == 401
    assert stale_signer.json()["code"] == "machine_auth_invalid"

    with Session(get_engine()) as session:
        nonce_count = session.scalar(
            select(func.count()).select_from(RemoteAgentReplayNonce)
        )
    assert nonce_count == 0


def test_machine_auth_hides_missing_and_short_secret_from_bad_signatures(
    client: TestClient,
    monkeypatch,
) -> None:
    """错误签名不得区分 credential 缺失、过短或正常配置。"""

    _, _, target = _seed_primary_target(client)
    body = heartbeat_body(target["id"])
    settings = get_settings()

    monkeypatch.delitem(
        settings.remote_agent_credentials,
        "test/agent-a/current",
    )
    missing = _post_heartbeat(
        client,
        body,
        signed_headers(target["id"], body),
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "machine_auth_invalid"

    short_secret = "short-secret"
    monkeypatch.setitem(
        settings.remote_agent_credentials,
        "test/agent-a/current",
        SecretStr(short_secret),
    )
    short_wrong_signature = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            secret="different-short-secret",
        ),
    )
    assert short_wrong_signature.status_code == 401
    assert short_wrong_signature.json()["code"] == "machine_auth_invalid"

    short_valid_signature = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            secret=short_secret,
        ),
    )
    assert short_valid_signature.status_code == 503
    assert short_valid_signature.json()["code"] == (
        "remote_agent_credential_too_short"
    )

    with Session(get_engine()) as session:
        nonce_count = session.scalar(
            select(func.count()).select_from(RemoteAgentReplayNonce)
        )
    assert nonce_count == 0


def test_registered_target_does_not_reload_unrelated_profile_file(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    """已登记 Target 的 list/heartbeat 只依赖 DB 与 secret 映射。"""

    _, environment, target = _seed_primary_target(client)
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "remote_target_profiles_file",
        str(tmp_path / "missing-profiles.json"),
    )

    listed = client.get(
        f"/api/environments/{environment['id']}/remote-targets"
    )
    assert listed.status_code == 200

    body = heartbeat_body(target["id"])
    accepted = _post_heartbeat(
        client,
        body,
        signed_headers(target["id"], body),
    )
    assert accepted.status_code == 200

    new_registration = client.post(
        f"/api/environments/{environment['id']}/remote-targets",
        json={
            "profile_key": "test-secondary",
            "display_name": "需要重新加载 profile",
        },
    )
    assert new_registration.status_code == 503
    assert new_registration.json()["code"] == (
        "remote_target_profile_configuration_invalid"
    )


def test_heartbeat_timing_configuration_preserves_offline_margin() -> None:
    """Platform 不得建议 Agent 在离线阈值之后或临界点才再次上报。"""

    with pytest.raises(ValidationError):
        Settings(
            remote_agent_next_heartbeat_seconds=30,
            remote_agent_offline_timeout_seconds=60,
        )


def test_machine_auth_database_work_does_not_block_asgi_event_loop(
    monkeypatch,
) -> None:
    """同步认证在线程池执行，等待数据库时其他请求仍可响应。"""

    started = Event()
    release = Event()

    def slow_authenticate(self, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        raise ServiceError(
            "machine_auth_invalid",
            "Machine authentication 请求无效。",
            401,
        )

    monkeypatch.setattr(
        MachineAuthService,
        "authenticate",
        slow_authenticate,
    )

    async def exercise() -> tuple[int, int, bool]:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://platform.test",
        ) as async_client:
            body = json.dumps(
                {
                    "target_id": str(uuid4()),
                    "agent_id": "remote-agent-a",
                    "agent_version": "0.1.0",
                    "capabilities": ["heartbeat"],
                    "reported_at": datetime.now(UTC).isoformat(),
                }
            ).encode("utf-8")
            heartbeat_task = asyncio.create_task(
                async_client.post(
                    HEARTBEAT_PATH,
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
            )
            await asyncio.to_thread(started.wait, 2)
            health = await asyncio.wait_for(
                async_client.get("/health"),
                timeout=2,
            )
            heartbeat_waiting = not heartbeat_task.done()
            release.set()
            heartbeat = await heartbeat_task
            return (
                health.status_code,
                heartbeat.status_code,
                heartbeat_waiting,
            )

    health_status, heartbeat_status, heartbeat_waiting = asyncio.run(
        exercise()
    )

    assert health_status == 200
    assert heartbeat_status == 401
    assert heartbeat_waiting is True


def test_future_timestamp_nonce_is_retained_until_signature_window_closes(
    client: TestClient,
    monkeypatch,
) -> None:
    """短 TTL 也不得早于未来 timestamp 的完整容差窗口清理 nonce。"""

    _, _, target = _seed_primary_target(client)
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "remote_agent_timestamp_tolerance_seconds",
        300,
    )
    monkeypatch.setattr(settings, "remote_agent_nonce_ttl_seconds", 60)
    request_epoch = int(time.time()) + 299
    body = heartbeat_body(target["id"])
    accepted = _post_heartbeat(
        client,
        body,
        signed_headers(
            target["id"],
            body,
            timestamp=str(request_epoch),
        ),
    )
    assert accepted.status_code == 200

    with Session(get_engine()) as session:
        replay = session.scalar(select(RemoteAgentReplayNonce))
    assert replay is not None
    assert replay.expires_at >= (
        replay.request_timestamp + timedelta(seconds=301)
    )
