"""Task 行锁作为状态变更与 conversation 写入的全局锁顺序测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from cloudhelm_platform_api.services.design_service import DesignService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.task_service import TaskService
from conftest import create_project, create_running_agent_run, create_task


def test_concurrent_pause_and_cancel_cannot_revive_cancelled_task(
    client: TestClient,
) -> None:
    """并发状态变更必须在 Task 锁后重验，cancelled 不得被旧 pause 覆盖。"""

    project = create_project(client, "Task 状态锁项目")
    task = create_task(client, project["id"], title="并发 pause/cancel")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    barrier = Barrier(2)

    def pause() -> str:
        with Session(get_engine()) as session:
            barrier.wait(timeout=10)
            try:
                return TaskService(session).pause_task(
                    UUID(task["id"]),
                    "pause-worker",
                ).status.value
            except ServiceError as exc:
                return exc.code

    def cancel() -> str:
        with Session(get_engine()) as session:
            barrier.wait(timeout=10)
            return TaskService(session).cancel_task(
                UUID(task["id"]),
                "cancel-worker",
            ).status.value

    with ThreadPoolExecutor(max_workers=2) as pool:
        pause_future = pool.submit(pause)
        cancel_future = pool.submit(cancel)
        outcomes = {
            pause_future.result(timeout=15),
            cancel_future.result(timeout=15),
        }

    assert "cancelled" in outcomes
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "cancelled"
    timeline = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    assert sum(event["event_type"] == "TaskCancelled" for event in timeline) == 1


def test_cancel_and_spawn_follow_task_then_conversation_lock_order(
    client: TestClient,
) -> None:
    """cancel 与 spawn 并发时不得死锁或遗留 active conversation。"""

    project = create_project(client, "Task/Conversation 锁项目")
    task = create_task(client, project["id"], title="并发 cancel/spawn")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    root_id = _root_id(task["id"])
    parent_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=str(root_id),
    )
    barrier = Barrier(2)

    def cancel() -> str:
        with Session(get_engine()) as session:
            barrier.wait(timeout=10)
            return TaskService(session).cancel_task(
                UUID(task["id"]),
                "cancel-worker",
            ).status.value

    def spawn() -> str:
        with Session(get_engine()) as session:
            barrier.wait(timeout=10)
            try:
                AgentConversationService(
                    session,
                    get_settings(),
                ).spawn_subagent(
                    parent_conversation_id=root_id,
                    agent_role="reviewer",
                    nickname=None,
                    objective="与取消并发的有界审查。",
                    expected_result="返回审查摘要。",
                    spawned_by_agent_run_id=UUID(parent_run["id"]),
                    fork_context=False,
                )
                session.commit()
                return "spawned"
            except ServiceError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel_future = pool.submit(cancel)
        spawn_future = pool.submit(spawn)
        outcomes = {
            cancel_future.result(timeout=15),
            spawn_future.result(timeout=15),
        }

    assert "cancelled" in outcomes
    assert outcomes & {"spawned", "task_not_running"}
    with Session(get_engine()) as session:
        task_record = session.get(Task, UUID(task["id"]))
        active = session.scalar(
            select(func.count(AgentConversation.id)).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.status == "active",
            )
        )
    assert task_record is not None
    assert task_record.status == "cancelled"
    assert active == 0


def test_design_review_and_spawn_share_task_first_lock_order(
    client: TestClient,
) -> None:
    """设计评审写 root context 时与 spawn 串行且都能完成。"""

    project = create_project(client, "评审/Conversation 锁项目")
    task = create_task(client, project["id"], title="并发 design/spawn")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    design_step = client.post(f"/api/tasks/{task['id']}/run-next")
    assert design_step.status_code == 200, design_step.text
    design_id = UUID(design_step.json()["technical_design"]["id"])
    root_id = _root_id(task["id"])
    parent_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=str(root_id),
    )
    barrier = Barrier(2)

    def approve_design() -> str:
        with Session(get_engine()) as session:
            barrier.wait(timeout=10)
            return DesignService(session).approve(
                design_id,
                "design-reviewer",
            ).status.value

    def spawn() -> str:
        with Session(get_engine()) as session:
            barrier.wait(timeout=10)
            try:
                AgentConversationService(
                    session,
                    get_settings(),
                ).spawn_subagent(
                    parent_conversation_id=root_id,
                    agent_role="reviewer",
                    nickname=None,
                    objective="并发核验设计评审结果。",
                    expected_result="返回审查摘要。",
                    spawned_by_agent_run_id=UUID(parent_run["id"]),
                    fork_context=False,
                )
                session.commit()
                return "spawned"
            except ServiceError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        approved = pool.submit(approve_design)
        spawned = pool.submit(spawn)
        assert approved.result(timeout=15) == "approved"
        assert spawned.result(timeout=15) in {
            "spawned",
            "task_not_running",
        }


def _root_id(task_id: str) -> UUID:
    """读取 Task 唯一 root conversation。"""

    with Session(get_engine()) as session:
        root_id = session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.task_id == UUID(task_id),
                AgentConversation.source_type == "root",
            )
        )
    assert root_id is not None
    return root_id
