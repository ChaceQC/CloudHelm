"""Subagent 工具权限 lineage、终态和幂等重放安全测试。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.schemas.common import RiskLevel
from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from cloudhelm_platform_api.services.tool_gateway_service import ToolGatewayService
from conftest import create_project, create_running_agent_run, create_task


def test_legacy_write_role_child_is_rejected_at_tool_time(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """升级前遗留的 coder child 也不能进入 Tool Gateway。"""

    task, root_id = _started_task_with_root(client, "遗留角色拒绝")
    parent_run = create_running_agent_run(
        task["id"],
        "coder",
        conversation_id=str(root_id),
    )
    with Session(get_engine()) as session:
        root = session.get(AgentConversation, root_id)
        assert root is not None
        child_id = uuid4()
        session.add(
            AgentConversation(
                id=child_id,
                task_id=UUID(task["id"]),
                parent_conversation_id=root_id,
                spawned_by_agent_run_id=UUID(parent_run["id"]),
                source_type="subagent",
                agent_role="coder",
                nickname="legacy-coder",
                objective="模拟升级前遗留的写角色 child。",
                depth=1,
                status="active",
                fork_mode="fresh",
                provider_name=root.provider_name,
                model_name=root.model_name,
                prompt_cache_key=f"legacy:{child_id}",
                items_json=[],
                turn_count=0,
            )
        )
        session.commit()
    child_run = create_running_agent_run(
        task["id"],
        "coder",
        conversation_id=str(child_id),
    )

    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": child_run["id"],
            "tool_name": "repo.write_file",
            "risk_level": "L1",
            "idempotency_key": "legacy-coder-write-denied",
            "reason": "验证遗留 child 运行时门禁。",
            "arguments": {
                "workspace_root": str(tmp_path),
                "path": "denied.txt",
                "content": "denied",
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "subagent_role_not_allowed"
    assert not (tmp_path / "denied.txt").exists()
    rejected = [
        event
        for event in client.get(
            f"/api/tasks/{task['id']}/timeline"
        ).json()["items"]
        if event["event_type"] == "ToolCallRejected"
    ][-1]
    assert rejected["payload"]["rejection_stage"] == "context"
    assert rejected["payload"]["error_code"] == "subagent_role_not_allowed"
    assert rejected["payload"]["tool_call_id"] is None


def test_terminal_child_cannot_call_tools(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """completed/failed/cancelled child 不得继续使用仍为 running 的旧 AgentRun。"""

    task, root_id = _started_task_with_root(client, "终态 child 拒绝")
    _, child_id = _spawn_child(task["id"], root_id, "planner", "reviewer")
    child_run = create_running_agent_run(
        task["id"],
        "reviewer",
        conversation_id=str(child_id),
    )
    with Session(get_engine()) as session:
        child = session.get(AgentConversation, child_id)
        assert child is not None
        child.status = "completed"
        child.completed_at = utc_now()
        session.commit()

    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": child_run["id"],
            "tool_name": "repo.list_files",
            "risk_level": "L0",
            "idempotency_key": "terminal-child-denied",
            "reason": "验证终态 conversation 门禁。",
            "arguments": {"workspace_root": str(tmp_path), "path": "."},
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_conversation_not_active"


def test_agent_run_cannot_bind_another_tasks_root_conversation(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """跨 Task root 误绑定不得被当作普通 root AgentRun 放行。"""

    task_a, _ = _started_task_with_root(client, "Task A")
    _, root_b = _started_task_with_root(client, "Task B")
    cross_task_run = create_running_agent_run(
        task_a["id"],
        "reviewer",
        conversation_id=str(root_b),
    )

    response = client.post(
        f"/api/tasks/{task_a['id']}/tool-gateway/call",
        json={
            "agent_run_id": cross_task_run["id"],
            "tool_name": "repo.list_files",
            "risk_level": "L0",
            "idempotency_key": "cross-task-root-denied",
            "reason": "验证 conversation Task 归属。",
            "arguments": {"workspace_root": str(tmp_path), "path": "."},
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_run_conversation_task_mismatch"


def test_recursive_lineage_intersects_every_ancestor_role(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """显式提高深度后，grandchild 也不能获得任一祖先缺少的工具。"""

    task, root_id = _started_task_with_root(client, "递归权限交集")
    parent_run = create_running_agent_run(
        task["id"],
        "coder",
        conversation_id=str(root_id),
    )
    settings = get_settings().model_copy(
        update={"agent_max_subagent_depth": 2}
    )
    with Session(get_engine()) as session:
        reviewer_child, _ = AgentConversationService(
            session,
            settings,
        ).spawn_subagent(
            parent_conversation_id=root_id,
            agent_role="reviewer",
            nickname=None,
            objective="审查父级实现证据。",
            expected_result="返回审查摘要。",
            spawned_by_agent_run_id=UUID(parent_run["id"]),
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
        security_child, _ = AgentConversationService(
            session,
            settings,
        ).spawn_subagent(
            parent_conversation_id=reviewer_child_id,
            agent_role="security",
            nickname=None,
            objective="核验安全证据。",
            expected_result="返回安全摘要。",
            spawned_by_agent_run_id=UUID(reviewer_run["id"]),
            fork_context=False,
        )
        session.commit()
        security_child_id = security_child.id
    security_run = create_running_agent_run(
        task["id"],
        "security",
        conversation_id=str(security_child_id),
    )

    denied = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": security_run["id"],
            "tool_name": "security.run_bandit",
            "risk_level": "L1",
            "idempotency_key": "recursive-lineage-denied",
            "reason": "验证全部祖先权限交集。",
            "arguments": {
                "workspace_root": str(tmp_path),
                "cwd": ".",
                "path": ".",
            },
        },
    )

    assert denied.status_code == 201, denied.text
    assert denied.json()["status"] == "failed"
    assert denied.json()["error_code"] == "subagent_tool_not_allowed"
    scope = denied.json()["audit_json"]["subagent_permission_scope"]
    assert scope["ancestor_roles"] == ["reviewer", "coder"]
    assert "security.run_bandit" not in scope["effective_allowed_tools"]


def test_idempotent_replay_rejects_changed_parent_permission_scope(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """旧成功 ToolCall 不得在父级权限收紧后按相同幂等键复用。"""

    subprocess.run(
        ["git", "init", "--initial-branch=main", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    task, root_id = _started_task_with_root(client, "幂等权限漂移")
    parent_run_id, child_id = _spawn_child(
        task["id"],
        root_id,
        "coder",
        "reviewer",
    )
    child_run = create_running_agent_run(
        task["id"],
        "reviewer",
        conversation_id=str(child_id),
    )
    body = {
        "agent_run_id": child_run["id"],
        "tool_name": "git.diff",
        "risk_level": "L0",
        "idempotency_key": "subagent-policy-drift",
        "reason": "验证幂等重放策略一致性。",
        "arguments": {"repo_root": str(tmp_path)},
    }

    first = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json=body,
    )
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "succeeded"

    with Session(get_engine()) as session:
        parent_run = session.get(AgentRun, parent_run_id)
        assert parent_run is not None
        parent_run.agent_type = "planner"
        session.commit()

    replay = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json=body,
    )
    assert replay.status_code == 409
    assert replay.json()["code"] == "idempotency_policy_conflict"
    with Session(get_engine()) as session:
        calls = list(
            session.scalars(
                select(ToolCall).where(
                    ToolCall.task_id == UUID(task["id"]),
                    ToolCall.idempotency_key == "subagent-policy-drift",
                )
            )
        )
    assert len(calls) == 1
    assert calls[0].status == "succeeded"
    rejected = [
        event
        for event in client.get(
            f"/api/tasks/{task['id']}/timeline"
        ).json()["items"]
        if event["event_type"] == "ToolCallRejected"
    ][-1]
    assert rejected["payload"]["rejection_stage"] == "replay"
    assert rejected["payload"]["error_code"] == "idempotency_policy_conflict"
    assert rejected["payload"]["tool_call_id"] == first.json()["id"]


def test_late_result_keeps_subagent_permission_scope(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 状态漂移后的失败审计仍保留 claim 时的权限范围。"""

    task, root_id = _started_task_with_root(client, "晚到结果权限审计")
    _, child_id = _spawn_child(task["id"], root_id, "planner", "reviewer")
    child_run = create_running_agent_run(
        task["id"],
        "reviewer",
        conversation_id=str(child_id),
    )
    started = Event()
    release = Event()
    gateway = client.app.state.tool_gateway
    original_execute = gateway.execute

    def delayed_execute(request):  # noqa: ANN001
        started.set()
        assert release.wait(timeout=10)
        return original_execute(request)

    monkeypatch.setattr(gateway, "execute", delayed_execute)

    def execute_call():
        with Session(get_engine(), expire_on_commit=False) as session:
            return ToolGatewayService(session, gateway).call_tool(
                UUID(task["id"]),
                ToolGatewayCallCreate(
                    agent_run_id=UUID(child_run["id"]),
                    tool_name="repo.list_files",
                    risk_level=RiskLevel.L0,
                    idempotency_key="subagent-late-result",
                    reason="验证晚到结果权限审计。",
                    arguments={
                        "workspace_root": str(tmp_path),
                        "path": ".",
                    },
                ),
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute_call)
        assert started.wait(timeout=10)
        paused = client.post(f"/api/tasks/{task['id']}/pause")
        assert paused.status_code == 200, paused.text
        release.set()
        result = future.result(timeout=10)

    assert result.status.value == "failed"
    assert result.error_code == "task_state_changed_during_tool_execution"
    scope = result.audit_json["subagent_permission_scope"]
    assert scope["child_role"] == "reviewer"
    assert scope["ancestor_roles"] == ["planner"]
    assert result.audit_json["execution_policy_fingerprint"]


def _started_task_with_root(
    client: TestClient,
    name: str,
) -> tuple[dict, UUID]:
    """创建 running Task、首个 root turn，并返回 root conversation。"""

    project = create_project(client, f"{name}项目")
    task = create_task(client, project["id"], title=name)
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
    return task, root_id


def _spawn_child(
    task_id: str,
    root_id: UUID,
    parent_role: str,
    child_role: str,
) -> tuple[UUID, UUID]:
    """创建绑定 root 的父运行和一个 active child conversation。"""

    parent_run = create_running_agent_run(
        task_id,
        parent_role,
        conversation_id=str(root_id),
    )
    with Session(get_engine()) as session:
        child, _ = AgentConversationService(
            session,
            get_settings(),
        ).spawn_subagent(
            parent_conversation_id=root_id,
            agent_role=child_role,
            nickname=None,
            objective="只执行当前测试指定的有界分析任务。",
            expected_result="返回结构化摘要和审计证据。",
            spawned_by_agent_run_id=UUID(parent_run["id"]),
            fork_context=False,
        )
        session.commit()
        child_id = child.id
    return UUID(parent_run["id"]), child_id
