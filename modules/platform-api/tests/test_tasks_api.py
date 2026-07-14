"""Task API 与任务事件测试。"""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from conftest import create_project, create_running_agent_run, create_task


def test_create_task_writes_task_created_event(client: TestClient) -> None:
    """验证创建任务写入真实 Task 和 TaskCreated 事件。"""

    project = create_project(client)
    task = create_task(client, project["id"])

    assert task["status"] == "created"
    assert task["current_phase"] == "Created"

    timeline = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    assert [event["event_type"] for event in timeline] == ["TaskCreated"]
    assert timeline[0]["payload"]["project_id"] == project["id"]


def test_task_pause_resume_cancel_write_events_and_validate_state(client: TestClient) -> None:
    """验证任务状态流转、非法流转和事件副作用。"""

    project = create_project(client)
    task = create_task(client, project["id"])

    pause = client.post(f"/api/tasks/{task['id']}/pause", json={"actor_id": "tester", "reason": "人工暂停"})
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"

    resume = client.post(f"/api/tasks/{task['id']}/resume", json={"actor_id": "tester"})
    assert resume.status_code == 200
    assert resume.json()["status"] == "created"
    assert resume.json()["current_phase"] == "Created"

    cancel = client.post(f"/api/tasks/{task['id']}/cancel", json={"actor_id": "tester"})
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert cancel.json()["current_phase"] == "Created"

    second_cancel = client.post(f"/api/tasks/{task['id']}/cancel", json={"actor_id": "tester"})
    assert second_cancel.status_code == 409
    assert second_cancel.json()["code"] == "invalid_task_transition"

    event_types = [event["event_type"] for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]]
    assert event_types == ["TaskCreated", "TaskPaused", "TaskResumed", "TaskCancelled"]


def test_create_task_requires_existing_project(client: TestClient) -> None:
    """验证任务创建会校验 project_id。"""

    response = client.post(
        "/api/tasks",
        json={
            "project_id": "00000000-0000-0000-0000-000000000001",
            "title": "无效任务",
            "description": "项目不存在。",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "project_not_found"


def test_pause_resume_preserves_created_status_and_phase(client: TestClient) -> None:
    """Created 任务暂停恢复后不得伪造为 running。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    paused = client.post(f"/api/tasks/{task['id']}/pause", json={"actor_id": "tester"})
    assert paused.status_code == 200
    assert paused.json()["current_phase"] == "Created"

    resumed = client.post(f"/api/tasks/{task['id']}/resume", json={"actor_id": "tester"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "created"
    assert resumed.json()["current_phase"] == "Created"


def test_cancel_task_closes_active_runs_calls_and_approvals(client: TestClient) -> None:
    """Task 进入 cancelled 后不能遗留可执行 AgentRun、ToolCall 或 pending Approval。"""

    project = create_project(client)
    task = create_task(client, project["id"], "取消清理")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    agent_run = client.post(
        f"/api/tasks/{task['id']}/agent-runs",
        json={"agent_type": "coder", "status": "pending"},
    ).json()
    approval = client.post(
        f"/api/tasks/{task['id']}/approvals",
        json={
            "action": "approve_local_commit",
            "risk_level": "L2",
            "reason": "等待任务取消测试",
            "requested_by_agent_run_id": agent_run["id"],
        },
    ).json()
    tool_call = client.post(
        f"/api/tasks/{task['id']}/tool-calls",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "git.commit",
            "risk_level": "L2",
            "arguments_json": {"paths": ["README.md"]},
            "status": "waiting_approval",
            "approval_id": approval["id"],
        },
    ).json()

    cancelled = client.post(f"/api/tasks/{task['id']}/cancel", json={"actor_id": "tester"})
    assert cancelled.status_code == 200
    assert cancelled.json()["current_phase"] == "RequirementClarifying"
    assert client.get(f"/api/agent-runs/{agent_run['id']}").json()["status"] == "cancelled"
    assert client.get(f"/api/tool-calls/{tool_call['id']}").json()["status"] == "cancelled"
    assert client.get(f"/api/approvals/{approval['id']}").json()["status"] == "expired"

    event_types = [event["event_type"] for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]]
    assert "AgentRunCancelled" in event_types
    assert "ToolCallCancelled" in event_types
    assert "ApprovalExpired" in event_types
    assert event_types[-1] == "TaskCancelled"
    cancelled_event = client.get(
        f"/api/tasks/{task['id']}/timeline"
    ).json()["items"][-1]
    assert cancelled_event["payload"]["current_phase"] == "RequirementClarifying"


def test_cancel_task_closes_active_root_and_child_conversations(
    client: TestClient,
) -> None:
    """取消 Task 时 root/child conversation 必须同步进入可审计终态。"""

    project = create_project(client, "会话取消项目")
    task = create_task(client, project["id"], "取消 Agent 会话")
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

    spawning_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=str(root_id),
    )
    with Session(get_engine()) as session:
        service = AgentConversationService(session, get_settings())
        child, _ = service.spawn_subagent(
            parent_conversation_id=root_id,
            agent_role="reviewer",
            nickname="Atlas",
            objective="核验当前任务取消时 child conversation 的生命周期闭环。",
            expected_result="返回取消前的会话状态证据。",
            spawned_by_agent_run_id=UUID(spawning_run["id"]),
            fork_context=False,
        )
        child_id = child.id
        session.commit()

    cancelled = client.post(
        f"/api/tasks/{task['id']}/cancel",
        json={"actor_id": "tester", "reason": "终止当前开发任务"},
    )
    assert cancelled.status_code == 200

    with Session(get_engine()) as session:
        conversations = {
            conversation.id: conversation
            for conversation in session.scalars(
                select(AgentConversation).where(
                    AgentConversation.id.in_([root_id, child_id])
                )
            )
        }
        assert set(conversations) == {root_id, child_id}
        assert conversations[root_id].status == "cancelled"
        assert conversations[root_id].completed_at is not None
        assert conversations[child_id].status == "cancelled"
        assert conversations[child_id].completed_at is not None

    timeline = client.get(
        f"/api/tasks/{task['id']}/timeline"
    ).json()["items"]
    stopped_events = {
        event["event_type"]: event
        for event in timeline
        if event["event_type"]
        in {"AgentConversationStopped", "SubagentStopped"}
    }
    assert set(stopped_events) == {
        "AgentConversationStopped",
        "SubagentStopped",
    }
    assert stopped_events["AgentConversationStopped"]["payload"] == {
        "conversation_id": str(root_id),
        "source_type": "root",
        "status": "cancelled",
        "reason": "终止当前开发任务",
    }
    assert stopped_events["SubagentStopped"]["payload"] == {
        "conversation_id": str(child_id),
        "source_type": "subagent",
        "status": "cancelled",
        "reason": "终止当前开发任务",
    }
    cancelled_event = next(
        event for event in timeline if event["event_type"] == "TaskCancelled"
    )
    assert cancelled_event["payload"]["cancelled_agent_conversations"] == 2
