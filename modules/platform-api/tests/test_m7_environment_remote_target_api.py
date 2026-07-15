"""M7 Environment 与 RemoteTarget API 黑盒/白盒测试。"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from conftest import M7_REMOTE_AGENT_SECRETS, create_project
from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.models.environment import Environment
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.remote_target import (
    RemoteAgentCredential,
    RemoteTarget,
)
from cloudhelm_platform_api.repositories.environment_repository import (
    EnvironmentRepository,
)
from cloudhelm_platform_api.repositories.remote_target_repository import (
    RemoteTargetRepository,
)
from cloudhelm_platform_api.providers.remote_target_profile_provider import (
    RemoteTargetProfileProvider,
)
from m7_remote_fixtures import create_environment, create_remote_target

_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_environment_create_validation_pagination_and_events(
    client: TestClient,
) -> None:
    """Environment API 覆盖正常、重复、非法输入、缺失归属和分页。"""

    project = create_project(client)
    staging = create_environment(client, project["id"], name="staging")
    demo = create_environment(
        client,
        project["id"],
        name="demo",
        environment_type="demo",
        base_url="https://demo.example.test/app",
    )

    assert staging["project_id"] == project["id"]
    assert staging["status"] == "active"
    assert staging["base_url"] == "https://staging.example.test/"
    assert "env_profile_ref" not in staging
    assert demo["environment_type"] == "demo"

    detail = client.get(f"/api/environments/{staging['id']}")
    assert detail.status_code == 200
    assert detail.json() == staging

    first_page = client.get(
        f"/api/projects/{project['id']}/environments",
        params={"limit": 1},
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 1
    assert first_payload["page"]["next_cursor"] == "1"

    second_page = client.get(
        f"/api/projects/{project['id']}/environments",
        params={
            "limit": 1,
            "cursor": first_payload["page"]["next_cursor"],
        },
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert {
        first_payload["items"][0]["id"],
        second_page.json()["items"][0]["id"],
    } == {staging["id"], demo["id"]}

    duplicate = client.post(
        f"/api/projects/{project['id']}/environments",
        json={
            "name": "staging",
            "environment_type": "staging",
            "base_url": "https://other.example.test",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "environment_name_conflict"

    for invalid_payload in (
        {
            "name": "production",
            "environment_type": "production",
            "base_url": "https://prod.example.test",
        },
        {
            "name": "Invalid-Name",
            "environment_type": "staging",
            "base_url": "https://invalid.example.test",
        },
        {
            "name": "hidden-profile",
            "environment_type": "staging",
            "base_url": "https://hidden.example.test",
            "env_profile_ref": "caller-controlled",
        },
        {
            "name": "plain-http",
            "environment_type": "staging",
            "base_url": "http://plain.example.test",
        },
        {
            "name": "sensitive-url",
            "environment_type": "staging",
            "base_url": (
                "https://user:password@sensitive.example.test/"
                "path?token=value#fragment"
            ),
        },
    ):
        invalid = client.post(
            f"/api/projects/{project['id']}/environments",
            json=invalid_payload,
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "validation_error"

    missing_project = client.post(
        f"/api/projects/{uuid4()}/environments",
        json={
            "name": "staging",
            "environment_type": "staging",
            "base_url": "https://missing.example.test",
        },
    )
    assert missing_project.status_code == 404
    assert missing_project.json()["code"] == "project_not_found"

    missing_detail = client.get(f"/api/environments/{uuid4()}")
    assert missing_detail.status_code == 404
    assert missing_detail.json()["code"] == "environment_not_found"

    invalid_cursor = client.get(
        f"/api/projects/{project['id']}/environments",
        params={"cursor": "-1"},
    )
    assert invalid_cursor.status_code == 422

    with Session(get_engine()) as session:
        stored = session.get(Environment, staging["id"])
        assert stored is not None
        assert stored.env_profile_ref is None
        events = list(
            session.scalars(
                select(EventLog)
                .where(EventLog.event_type == "EnvironmentCreated")
                .order_by(EventLog.created_at)
            )
        )

    assert len(events) == 2
    assert {event.payload["environment_id"] for event in events} == {
        staging["id"],
        demo["id"],
    }
    assert all(event.task_id is None for event in events)


def test_remote_target_profile_registration_redacts_sensitive_data(
    client: TestClient,
) -> None:
    """RemoteTarget 只接受 profile key，响应和事件不泄露连接凭据。"""

    project = create_project(client)
    environment = create_environment(client, project["id"])
    target = create_remote_target(client, environment["id"])

    assert target["environment_id"] == environment["id"]
    assert target["agent_id"] == "remote-agent-a"
    assert target["endpoint_display"] == "https://<redacted>:9443"
    assert target["status"] == "offline"
    assert target["capabilities"] == []
    assert len(target["credential_fingerprints"]) == 5
    assert all(
        _FINGERPRINT.fullmatch(fingerprint)
        for fingerprint in target["credential_fingerprints"]
    )
    assert "agent_endpoint" not in target
    assert "credential_ref" not in target

    serialized = str(target)
    assert "agent-a.example.test" not in serialized
    assert all(
        secret not in serialized
        for secret in M7_REMOTE_AGENT_SECRETS.values()
    )

    listed = client.get(
        f"/api/environments/{environment['id']}/remote-targets"
    )
    assert listed.status_code == 200
    assert listed.json()["items"] == [target]

    with Session(get_engine()) as session:
        stored = session.get(RemoteTarget, target["id"])
        assert stored is not None
        assert stored.agent_endpoint == "https://agent-a.example.test:9443"
        assert stored.credential_ref == "profile:test-primary"
        credentials = list(
            session.scalars(
                select(RemoteAgentCredential)
                .where(RemoteAgentCredential.target_id == stored.id)
                .order_by(RemoteAgentCredential.key_id)
            )
        )
        event = session.scalar(
            select(EventLog).where(
                EventLog.event_type == "RemoteTargetRegistered"
            )
        )

    assert len(credentials) == 5
    assert all(
        _FINGERPRINT.fullmatch(item.secret_fingerprint)
        for item in credentials
    )
    assert event is not None
    assert event.payload["project_id"] == project["id"]
    assert event.payload["environment_id"] == environment["id"]
    event_text = str(event.payload)
    assert "agent-a.example.test" not in event_text
    assert "credential" not in event_text.lower()
    assert all(
        secret not in event_text
        for secret in M7_REMOTE_AGENT_SECRETS.values()
    )


def test_remote_target_rejects_unsafe_unknown_duplicate_and_inactive_inputs(
    client: TestClient,
) -> None:
    """RemoteTarget 注册覆盖额外敏感字段、未知 profile、重复和禁用环境。"""

    project = create_project(client)
    environment = create_environment(client, project["id"])

    unsafe = client.post(
        f"/api/environments/{environment['id']}/remote-targets",
        json={
            "profile_key": "test-primary",
            "display_name": "不安全目标",
            "agent_endpoint": "https://caller.example.test",
            "credential": "caller-secret",
        },
    )
    assert unsafe.status_code == 422
    assert unsafe.json()["code"] == "validation_error"
    assert "caller-secret" not in unsafe.text
    assert "caller.example.test" not in unsafe.text

    unknown = client.post(
        f"/api/environments/{environment['id']}/remote-targets",
        json={
            "profile_key": "missing-profile",
            "display_name": "未知目标",
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "remote_target_profile_not_found"

    create_remote_target(client, environment["id"])
    duplicate = client.post(
        f"/api/environments/{environment['id']}/remote-targets",
        json={
            "profile_key": "test-primary",
            "display_name": "重复目标",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "remote_target_conflict"

    with Session(get_engine()) as session:
        stored_environment = session.get(Environment, environment["id"])
        assert stored_environment is not None
        stored_environment.status = "disabled"
        session.commit()

    inactive = client.post(
        f"/api/environments/{environment['id']}/remote-targets",
        json={
            "profile_key": "test-secondary",
            "display_name": "禁用环境目标",
        },
    )
    assert inactive.status_code == 409
    assert inactive.json()["code"] == "environment_not_active"

    missing_environment = client.post(
        f"/api/environments/{uuid4()}/remote-targets",
        json={
            "profile_key": "test-primary",
            "display_name": "缺失环境目标",
        },
    )
    assert missing_environment.status_code == 404
    assert missing_environment.json()["code"] == "environment_not_found"

    missing_list = client.get(
        f"/api/environments/{uuid4()}/remote-targets"
    )
    assert missing_list.status_code == 404
    assert missing_list.json()["code"] == "environment_not_found"


def test_concurrent_environment_name_conflict_returns_stable_409(
    client: TestClient,
    monkeypatch,
) -> None:
    """两个并发请求同时通过查重时，数据库唯一约束仍映射为 409。"""

    project = create_project(client)
    barrier = Barrier(2)
    original = EnvironmentRepository.get_by_project_name

    def synchronized_lookup(
        repository: EnvironmentRepository,
        project_id,
        name: str,
    ):
        result = original(repository, project_id, name)
        if result is None:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(
        EnvironmentRepository,
        "get_by_project_name",
        synchronized_lookup,
    )

    def create_once() -> tuple[int, str]:
        with TestClient(
            create_app(),
            raise_server_exceptions=False,
        ) as concurrent_client:
            response = concurrent_client.post(
                f"/api/projects/{project['id']}/environments",
                json={
                    "name": "race-environment",
                    "environment_type": "staging",
                    "base_url": "https://race.example.test",
                },
            )
            return response.status_code, response.json().get("code", "ok")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create_once(), range(2)))

    assert sorted(status for status, _ in results) == [201, 409]
    assert sorted(code for _, code in results) == [
        "environment_name_conflict",
        "ok",
    ]


def test_concurrent_remote_target_conflict_returns_stable_409(
    client: TestClient,
    monkeypatch,
) -> None:
    """并发注册同一 Agent 时由 PostgreSQL 唯一约束稳定裁决。"""

    project = create_project(client)
    environment = create_environment(client, project["id"])
    barrier = Barrier(2)
    original = RemoteTargetRepository.get_by_environment_agent

    def synchronized_lookup(
        repository: RemoteTargetRepository,
        environment_id,
        agent_id: str,
    ):
        result = original(repository, environment_id, agent_id)
        if result is None:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(
        RemoteTargetRepository,
        "get_by_environment_agent",
        synchronized_lookup,
    )

    def create_once() -> tuple[int, str]:
        with TestClient(
            create_app(),
            raise_server_exceptions=False,
        ) as concurrent_client:
            response = concurrent_client.post(
                f"/api/environments/{environment['id']}/remote-targets",
                json={
                    "profile_key": "test-primary",
                    "display_name": "并发目标",
                },
            )
            return response.status_code, response.json().get("code", "ok")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create_once(), range(2)))

    assert sorted(status for status, _ in results) == [201, 409]
    assert sorted(code for _, code in results) == [
        "ok",
        "remote_target_conflict",
    ]


def test_committed_remote_target_profile_example_is_valid_and_secret_free() -> None:
    """非敏感示例必须能被 provider 读取，且不包含 machine secret 字段。"""

    example_path = (
        REPOSITORY_ROOT
        / "modules"
        / "platform-api"
        / "remote-target-profiles.example.json"
    )
    raw = json.loads(example_path.read_text(encoding="utf-8"))
    settings = get_settings().model_copy(
        update={
            "remote_target_profiles": {},
            "remote_target_profiles_file": str(example_path),
        }
    )
    profile = RemoteTargetProfileProvider(settings).get_profile(
        "demo-linux-agent"
    )

    assert profile.agent_id == "remote-agent-demo"
    assert profile.agent_endpoint.scheme == "https"
    assert set(raw) == {"profiles"}
    assert '"secret"' not in example_path.read_text(encoding="utf-8").lower()
