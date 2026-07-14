"""Codex CLI 式 subagent 数量与深度边界测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from conftest import create_project, create_running_agent_run, create_task


def test_seventh_active_subagent_is_rejected(client: TestClient) -> None:
    """单 Task 已有 6 个 active child 时必须拒绝第 7 个。"""

    project = create_project(client, "子 Agent 配额项目")
    task = create_task(client, project["id"], title="验证 active child 上限")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200

    with Session(get_engine()) as session:
        root_id = session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "root",
            )
        )
    assert root_id is not None
    parent_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=str(root_id),
    )

    with Session(get_engine()) as session:
        settings = get_settings()
        service = AgentConversationService(session, settings)
        for index in range(settings.agent_max_subagent_threads):
            service.spawn_subagent(
                parent_conversation_id=root_id,
                agent_role="reviewer",
                nickname=f"reviewer-{index + 1}",
                objective=f"独立核验第 {index + 1} 组只读证据。",
                expected_result="返回有界审查摘要。",
                spawned_by_agent_run_id=UUID(parent_run["id"]),
                fork_context=False,
            )

        with pytest.raises(ServiceError) as limit_error:
            service.spawn_subagent(
                parent_conversation_id=root_id,
                agent_role="reviewer",
                nickname="reviewer-7",
                objective="继续创建超出上限的只读审查 child。",
                expected_result="返回有界审查摘要。",
                spawned_by_agent_run_id=UUID(parent_run["id"]),
                fork_context=False,
            )

        assert limit_error.value.code == "subagent_thread_limit_exceeded"
        assert session.scalar(
            select(func.count(AgentConversation.id)).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "subagent",
                AgentConversation.status == "active",
            )
        ) == settings.agent_max_subagent_threads


def test_concurrent_spawns_share_one_task_thread_limit(
    client: TestClient,
) -> None:
    """并发 spawn 必须通过 root 行锁串行检查 Task 级 active 上限。"""

    project = create_project(client, "子 Agent 并发配额项目")
    task = create_task(client, project["id"], title="验证并发 child 上限")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    with Session(get_engine()) as session:
        root_id = session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "root",
            )
        )
    assert root_id is not None
    parent_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=str(root_id),
    )
    settings = get_settings().model_copy(
        update={"agent_max_subagent_threads": 1}
    )
    barrier = Barrier(2)

    def spawn(index: int) -> str:
        with Session(get_engine()) as session:
            service = AgentConversationService(session, settings)
            barrier.wait(timeout=10)
            try:
                service.spawn_subagent(
                    parent_conversation_id=root_id,
                    agent_role="reviewer",
                    nickname=f"parallel-{index}",
                    objective=f"并发核验第 {index} 组只读证据。",
                    expected_result="返回有界审查摘要。",
                    spawned_by_agent_run_id=UUID(parent_run["id"]),
                    fork_context=False,
                )
                session.commit()
                return "spawned"
            except ServiceError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(spawn, (1, 2)))

    assert results == ["spawned", "subagent_thread_limit_exceeded"]
    with Session(get_engine()) as session:
        assert session.scalar(
            select(func.count(AgentConversation.id)).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "subagent",
                AgentConversation.status == "active",
            )
        ) == 1


def test_paused_task_cannot_spawn_subagent(client: TestClient) -> None:
    """Task 暂停后，即使父 AgentRun 仍 running 也不得创建 child。"""

    project = create_project(client, "暂停子 Agent 项目")
    task = create_task(client, project["id"], title="验证暂停 spawn 门禁")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    with Session(get_engine()) as session:
        root_id = session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "root",
            )
        )
    assert root_id is not None
    parent_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=str(root_id),
    )
    assert client.post(f"/api/tasks/{task['id']}/pause").status_code == 200

    with Session(get_engine()) as session:
        service = AgentConversationService(session, get_settings())
        with pytest.raises(ServiceError) as paused_error:
            service.spawn_subagent(
                parent_conversation_id=root_id,
                agent_role="reviewer",
                nickname=None,
                objective="暂停后不应创建的 child。",
                expected_result="不应产生结果。",
                spawned_by_agent_run_id=UUID(parent_run["id"]),
                fork_context=False,
            )

    assert paused_error.value.code == "task_not_running"


def test_parent_child_cannot_complete_before_active_descendant(
    client: TestClient,
) -> None:
    """递归委派时必须先收口最深 child，再结束父 child。"""

    project = create_project(client, "子 Agent 后代项目")
    task = create_task(client, project["id"], title="验证后代完成顺序")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    with Session(get_engine()) as session:
        root_id = session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "root",
            )
        )
    assert root_id is not None
    root_run = create_running_agent_run(
        task["id"],
        "coder",
        conversation_id=str(root_id),
    )
    settings = get_settings().model_copy(
        update={"agent_max_subagent_depth": 2}
    )
    with Session(get_engine()) as session:
        service = AgentConversationService(session, settings)
        reviewer_child, _ = service.spawn_subagent(
            parent_conversation_id=root_id,
            agent_role="reviewer",
            nickname=None,
            objective="审查父级实现。",
            expected_result="返回审查摘要。",
            spawned_by_agent_run_id=UUID(root_run["id"]),
            fork_context=False,
        )
        session.commit()
        reviewer_child_id = reviewer_child.id
    reviewer_run = create_running_agent_run(
        task["id"],
        "reviewer",
        conversation_id=str(reviewer_child_id),
    )
    with Session(get_engine()) as session:
        service = AgentConversationService(session, settings)
        service.spawn_subagent(
            parent_conversation_id=reviewer_child_id,
            agent_role="security",
            nickname=None,
            objective="核验安全证据。",
            expected_result="返回安全摘要。",
            spawned_by_agent_run_id=UUID(reviewer_run["id"]),
            fork_context=False,
        )
        run = session.get(
            AgentRun,
            UUID(reviewer_run["id"]),
        )
        assert run is not None
        run.status = "succeeded"
        session.commit()

    with Session(get_engine()) as session:
        service = AgentConversationService(session, settings)
        with pytest.raises(ServiceError) as descendant_error:
            service.complete_subagent(
                reviewer_child_id,
                status="completed",
                summary="父 child 尝试提前完成。",
            )

    assert descendant_error.value.code == "subagent_descendants_active"
