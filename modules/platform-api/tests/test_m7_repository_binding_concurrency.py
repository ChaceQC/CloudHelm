"""M7-2B1 RepositoryBinding identity、回滚与并发测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from m7_repository_binding_fixture import event_count
from conftest import create_project


@pytest.mark.parametrize(
    "second_profile",
    ["test-primary", "test-owner-case-conflict"],
)
def test_repository_identity_conflicts_return_stable_409(
    client: TestClient,
    second_profile: str,
) -> None:
    """External ID 与大小写不敏感 owner/name 冲突均返回稳定 409。"""

    first_project = create_project(client, "仓库绑定项目一")
    second_project = create_project(client, "仓库绑定项目二")
    first = client.put(
        f"/api/projects/{first_project['id']}/repository-binding",
        json={"profile_key": "test-primary"},
    )
    assert first.status_code == 200

    conflict = client.put(
        f"/api/projects/{second_project['id']}/repository-binding",
        json={"profile_key": second_profile},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "repository_binding_conflict"


def test_conflicting_update_rolls_back_existing_binding_and_event(
    client: TestClient,
) -> None:
    """更新命中其他 Project identity 时原 Binding 与事件保持不变。"""

    first_project = create_project(client, "冲突回滚项目一")
    second_project = create_project(client, "冲突回滚项目二")
    first_path = (
        f"/api/projects/{first_project['id']}/repository-binding"
    )
    second_path = (
        f"/api/projects/{second_project['id']}/repository-binding"
    )
    first = client.put(
        first_path,
        json={"profile_key": "test-secondary"},
    )
    second = client.put(
        second_path,
        json={"profile_key": "test-primary"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    configured_events = event_count("RepositoryBindingConfigured")

    conflict = client.put(
        first_path,
        json={"profile_key": "test-primary"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "repository_binding_conflict"
    after = client.get(first_path)
    assert after.status_code == 200
    assert after.json() == first.json()
    assert event_count("RepositoryBindingConfigured") == configured_events


def test_concurrent_identical_puts_return_one_binding(
    client: TestClient,
) -> None:
    """首次创建以 Project 行为 mutex，并发相同 PUT 返回同一 Binding。"""

    project = create_project(client)
    path = f"/api/projects/{project['id']}/repository-binding"
    barrier = Barrier(2)

    def put_binding() -> tuple[int, dict]:
        with TestClient(create_app()) as concurrent_client:
            barrier.wait(timeout=10)
            response = concurrent_client.put(
                path,
                json={"profile_key": "test-primary"},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: put_binding(), range(2)))

    assert [status for status, _ in results] == [200, 200]
    assert len({payload["id"] for _, payload in results}) == 1
    assert event_count("RepositoryBindingConfigured") == 1


def test_concurrent_projects_compete_for_repository_identity(
    client: TestClient,
) -> None:
    """不同 Project 并发绑定同一 identity 时一个成功、一个稳定冲突。"""

    projects = [
        create_project(client, "并发仓库身份项目一"),
        create_project(client, "并发仓库身份项目二"),
    ]
    barrier = Barrier(2)

    def put_binding(project_id: str) -> tuple[int, dict]:
        with TestClient(
            create_app(),
            raise_server_exceptions=False,
        ) as concurrent_client:
            barrier.wait(timeout=10)
            response = concurrent_client.put(
                f"/api/projects/{project_id}/repository-binding",
                json={"profile_key": "test-primary"},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                put_binding,
                [project["id"] for project in projects],
            )
        )

    assert sorted(status for status, _ in results) == [200, 409]
    conflict_payload = next(
        payload for status, payload in results if status == 409
    )
    assert conflict_payload["code"] == "repository_binding_conflict"
    with Session(get_engine()) as session:
        assert session.scalar(
            select(func.count(ProjectRepositoryBinding.id))
        ) == 1


def test_concurrent_binding_identity_swap_returns_stable_conflicts(
    client: TestClient,
) -> None:
    """两个已绑定 Project 反向交换 identity 时不形成 500 或数据库死锁。"""

    first_project = create_project(client, "并发交换项目一")
    second_project = create_project(client, "并发交换项目二")
    bindings = [
        (
            first_project,
            "test-primary",
            "test-secondary",
        ),
        (
            second_project,
            "test-secondary",
            "test-primary",
        ),
    ]
    for project, initial_profile, _ in bindings:
        response = client.put(
            f"/api/projects/{project['id']}/repository-binding",
            json={"profile_key": initial_profile},
        )
        assert response.status_code == 200
    configured_events = event_count("RepositoryBindingConfigured")
    barrier = Barrier(2)

    def swap_binding(item: tuple[dict, str, str]) -> tuple[int, dict]:
        project, _, target_profile = item
        with TestClient(
            create_app(),
            raise_server_exceptions=False,
        ) as concurrent_client:
            barrier.wait(timeout=10)
            response = concurrent_client.put(
                f"/api/projects/{project['id']}/repository-binding",
                json={"profile_key": target_profile},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(swap_binding, bindings))

    assert [status for status, _ in results] == [409, 409]
    assert {
        payload["code"] for _, payload in results
    } == {"repository_binding_conflict"}
    assert event_count("RepositoryBindingConfigured") == configured_events
    for project, initial_profile, _ in bindings:
        response = client.get(
            f"/api/projects/{project['id']}/repository-binding"
        )
        assert response.status_code == 200
        assert response.json()["profile_key"] == initial_profile
