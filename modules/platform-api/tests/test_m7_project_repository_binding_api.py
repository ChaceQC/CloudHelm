"""M7-2B1 ProjectRepositoryBinding PUT/GET 黑盒契约测试。"""

import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.providers.repository_profile_provider import (
    RepositoryProfileProvider,
)
from m7_repository_binding_fixture import (
    REPOSITORY_BINDING_EVENT_FIELDS,
)
from conftest import create_project

PUBLIC_BINDING_FIELDS = {
    "id",
    "project_id",
    "provider",
    "profile_key",
    "repository_external_id",
    "repository_owner",
    "repository_name",
    "default_branch",
    "workflow_id",
    "release_ref_prefix",
    "status",
    "created_at",
    "updated_at",
}


def test_put_and_get_repository_binding_expose_only_public_fields(
    client: TestClient,
) -> None:
    """PUT 物化服务端配置，GET 只返回数据库中的安全字段。"""

    project = create_project(client)
    response = client.put(
        f"/api/projects/{project['id']}/repository-binding",
        json={"profile_key": "test-primary"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == PUBLIC_BINDING_FIELDS
    assert payload["project_id"] == project["id"]
    assert payload["provider"] == "gitea"
    assert payload["repository_external_id"] == "repo-42"
    assert payload["repository_owner"] == "CloudHelm"
    assert payload["repository_name"] == "Sample-API"
    assert payload["default_branch"] == "dev"
    assert payload["workflow_id"] == ".gitea/workflows/ci.yml"
    assert payload["release_ref_prefix"] == "refs/heads/cloudhelm/candidates"
    assert payload["status"] == "active"

    get_response = client.get(
        f"/api/projects/{project['id']}/repository-binding"
    )
    assert get_response.status_code == 200
    assert get_response.json() == payload

    with Session(get_engine()) as session:
        binding = session.scalar(
            select(ProjectRepositoryBinding).where(
                ProjectRepositoryBinding.project_id == UUID(project["id"])
            )
        )
        event = session.scalar(
            select(EventLog)
            .where(EventLog.event_type == "RepositoryBindingConfigured")
            .order_by(EventLog.created_at.desc())
        )
        assert binding is not None
        assert binding.clone_url.endswith("/CloudHelm/Sample-API.git")
        assert binding.credential_ref == "test/repository/primary"
        assert event is not None
        assert event.task_id is None
        assert event.actor_type == "system"
        assert event.actor_id == "repository-profile"
        assert set(event.payload) == REPOSITORY_BINDING_EVENT_FIELDS
        assert event.payload["created"] is True
        assert event.payload["configuration_changed"] is False
        assert event.payload["stale_candidate_ids"] == []
        assert event.payload["expired_approval_ids"] == []
        serialized_event = json.dumps(
            event.payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        assert "clone_url" not in serialized_event
        assert "credential_ref" not in serialized_event
        assert "test-repository-primary-token" not in serialized_event


@pytest.mark.parametrize(
    "extra_field",
    [
        "clone_url",
        "credential_ref",
        "workflow_id",
        "remote",
        "refspec",
        "token",
    ],
)
def test_put_repository_binding_rejects_caller_controlled_configuration(
    client: TestClient,
    extra_field: str,
) -> None:
    """普通调用方提交 URL、凭据或 workflow 等额外字段时返回 422。"""

    project = create_project(client)
    response = client.put(
        f"/api/projects/{project['id']}/repository-binding",
        json={
            "profile_key": "test-primary",
            extra_field: "caller-controlled",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_repository_binding_not_found_contracts(
    client: TestClient,
) -> None:
    """区分 Project、Binding 和 RepositoryProfile 不存在。"""

    missing_project = client.put(
        f"/api/projects/{uuid4()}/repository-binding",
        json={"profile_key": "test-primary"},
    )
    assert missing_project.status_code == 404
    assert missing_project.json()["code"] == "project_not_found"
    missing_project_get = client.get(
        f"/api/projects/{uuid4()}/repository-binding"
    )
    assert missing_project_get.status_code == 404
    assert missing_project_get.json()["code"] == "project_not_found"

    project = create_project(client)
    missing_binding = client.get(
        f"/api/projects/{project['id']}/repository-binding"
    )
    assert missing_binding.status_code == 404
    assert missing_binding.json()["code"] == "repository_binding_not_found"

    missing_profile = client.put(
        f"/api/projects/{project['id']}/repository-binding",
        json={"profile_key": "unknown-profile"},
    )
    assert missing_profile.status_code == 422
    assert missing_profile.json()["code"] == "repository_profile_not_found"


def test_repository_binding_rejects_missing_credential(
    client: TestClient,
) -> None:
    """Profile 引用的 credential 缺失时不创建 Binding。"""

    project = create_project(client)
    response = client.put(
        f"/api/projects/{project['id']}/repository-binding",
        json={"profile_key": "test-missing-credential"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "repository_profile_unusable"
    with Session(get_engine()) as session:
        assert (
            session.scalar(
                select(func.count(ProjectRepositoryBinding.id)).where(
                    ProjectRepositoryBinding.project_id
                    == UUID(project["id"])
                )
            )
            == 0
        )


def test_cors_preflight_allows_repository_binding_put(
    client: TestClient,
) -> None:
    """Desktop WebView 的 PUT 预检必须由 CORS 明确允许。"""

    project = create_project(client)
    response = client.options(
        f"/api/projects/{project['id']}/repository-binding",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_get_does_not_reload_repository_profile(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """历史 Binding GET 在 profile 来源不可用时仍只读数据库成功。"""

    project = create_project(client)
    path = f"/api/projects/{project['id']}/repository-binding"
    created = client.put(path, json={"profile_key": "test-primary"})
    assert created.status_code == 200

    def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("GET 不应读取 RepositoryProfile")

    monkeypatch.setattr(
        RepositoryProfileProvider,
        "get_profile",
        fail_if_loaded,
    )
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == created.json()
