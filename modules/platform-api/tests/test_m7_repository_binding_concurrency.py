"""M7-2B1 RepositoryBinding identity、回滚与并发测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.providers.repository_profile_provider import (
    RepositoryProfileProvider,
)
from cloudhelm_platform_api.services.repository_binding_snapshot import (
    internal_snapshot_hash_from_binding,
)
from m7_release_candidate_api_fixture import (
    seed_release_candidate_dependencies,
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


def test_concurrent_binding_put_and_candidate_post_preserve_freshness(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """先启动 PUT 事务再创建 Candidate，失效时间仍不得早于创建时间。"""

    seeded = seed_release_candidate_dependencies(client)
    candidate_path = (
        f"/api/tasks/{seeded['task_id']}/release-candidate"
    )
    binding_path = (
        f"/api/projects/{seeded['project_id']}/repository-binding"
    )
    profile_lookup_started = Event()
    continue_profile_lookup = Event()
    original_get_profile = RepositoryProfileProvider.get_profile

    def delayed_get_profile(
        provider: RepositoryProfileProvider,
        profile_key: str,
    ):
        """在 PUT 已开启事务但尚未锁 Binding 时让 Candidate 完成创建。"""

        if profile_key == "test-primary-drift":
            profile_lookup_started.set()
            assert continue_profile_lookup.wait(timeout=10)
        return original_get_profile(provider, profile_key)

    monkeypatch.setattr(
        RepositoryProfileProvider,
        "get_profile",
        delayed_get_profile,
    )

    def create_candidate() -> tuple[int, dict]:
        with TestClient(create_app()) as concurrent_client:
            response = concurrent_client.post(candidate_path, json={})
            return response.status_code, response.json()

    def drift_binding() -> tuple[int, dict]:
        with TestClient(create_app()) as concurrent_client:
            response = concurrent_client.put(
                binding_path,
                json={"profile_key": "test-primary-drift"},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        binding_future = pool.submit(drift_binding)
        assert profile_lookup_started.wait(timeout=10)
        try:
            candidate_result = create_candidate()
        finally:
            continue_profile_lookup.set()
        binding_result = binding_future.result()

    assert candidate_result[0] == 201
    assert binding_result[0] == 200
    with Session(get_engine()) as session:
        binding = session.get(
            ProjectRepositoryBinding,
            UUID(seeded["repository_binding_id"]),
        )
        candidate = session.scalar(
            select(ReleaseCandidate).where(
                ReleaseCandidate.task_id == UUID(seeded["task_id"])
            )
        )
        assert binding is not None
        assert candidate is not None
        current_hash = internal_snapshot_hash_from_binding(binding)
        approval = session.get(
            ApprovalRequest,
            candidate.approval_id,
        )
        assert approval is not None
        if candidate.status in {"pending_approval", "approved"}:
            assert candidate.binding_snapshot_sha256 == current_hash
            assert approval.status == "pending"
        else:
            assert candidate.status == "stale"
            assert candidate.binding_snapshot_sha256 != current_hash
            assert candidate.updated_at >= candidate.created_at
            assert approval.status == "expired"
            assert approval.decided_at is not None
            assert approval.decided_at >= approval.created_at
