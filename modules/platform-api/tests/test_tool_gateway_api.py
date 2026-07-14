"""M5 Tool Gateway API 黑盒与事务副作用测试。"""

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cloudhelm_tool_gateway import create_default_gateway
from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)

from conftest import create_project, create_running_agent_run, create_task


def _task(client: TestClient) -> dict:
    """创建测试任务。"""

    project = create_project(client, "Tool Gateway 项目")
    task = create_task(client, project["id"], "执行 Tool Gateway")
    started = client.post(f"/api/tasks/{task['id']}/start")
    assert started.status_code == 200, started.text
    return started.json()["task"]


def test_list_tool_gateway_tools(client: TestClient) -> None:
    """控制台能读取真实工具注册表。"""

    response = client.get("/api/tool-gateway/tools")
    assert response.status_code == 200, response.text
    declarations = response.json()["items"]
    tool_names = {item["name"] for item in declarations}
    assert {"repo.read_file", "sandbox.run_command", "git.commit", "approval.request_remote_action"} <= tool_names
    assert all(item["result_schema"]["title"] == "ToolCallResult" for item in declarations)


def test_repo_tool_gateway_call_writes_tool_call_and_events(client: TestClient, tmp_path: Path) -> None:
    """通过 API 调用 Repo Tool 会写 ToolCall 和事件。"""

    task = _task(client)
    agent_run = create_running_agent_run(task["id"], "coder")
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "repo.write_file",
            "risk_level": "L1",
            "idempotency_key": "repo-write-1",
            "reason": "测试受控写入",
            "arguments": {
                "workspace_root": str(tmp_path),
                "path": "notes/result.md",
                "content": "CloudHelm M5",
                "create_parent": True,
            },
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["tool_name"] == "repo.write_file"
    assert payload["result_summary"]
    assert payload["audit_json"]["arguments_hash"].startswith("sha256:")
    assert payload["audit_json"]["agent_type"] == "coder"
    assert (tmp_path / "notes" / "result.md").read_text(encoding="utf-8") == "CloudHelm M5"
    with get_engine().connect() as connection:
        stored = connection.execute(
            text("SELECT arguments_json, audit_json FROM tool_calls WHERE id = CAST(:id AS uuid)"),
            {"id": payload["id"]},
        ).mappings().one()
    assert stored["arguments_json"]["content"]["redacted"] is True
    assert stored["arguments_json"]["content"]["sha256"].startswith("sha256:")
    assert stored["audit_json"]["status"] == "succeeded"

    timeline = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    event_types = {event["event_type"] for event in timeline}
    assert {"ToolCallStarted", "ToolCallSucceeded"} <= event_types


def test_sandbox_tool_gateway_call_records_output_summary(client: TestClient, tmp_path: Path) -> None:
    """Sandbox Tool 输出应摘要化写入 ToolCall。"""

    task = _task(client)
    agent_run = create_running_agent_run(task["id"], "tester")
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "sandbox.run_command",
            "risk_level": "L1",
            "idempotency_key": "sandbox-1",
            "reason": "测试命令执行",
            "arguments": {"workspace_root": str(tmp_path), "command": ["python", "-c", "print('api-sandbox-ok')"]},
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert "api-sandbox-ok" in payload["stdout_summary"]


def test_subagent_tool_permissions_are_parent_child_intersection(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """child 工具必须同时被自身角色和全部父级角色允许。"""

    task = _task(client)
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
        child, _ = AgentConversationService(session, get_settings()).spawn_subagent(
            parent_conversation_id=root_id,
            agent_role="reviewer",
            nickname=None,
            objective="只审查受控 workspace 的路径和 diff 证据。",
            expected_result="返回结构化审查摘要。",
            spawned_by_agent_run_id=UUID(parent_run["id"]),
            fork_context=False,
        )
        session.commit()
        child_id = child.id
    child_run = create_running_agent_run(
        task["id"],
        "reviewer",
        conversation_id=str(child_id),
    )

    denied = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": child_run["id"],
            "tool_name": "git.diff",
            "risk_level": "L0",
            "idempotency_key": "subagent-parent-intersection-denied",
            "reason": "验证父级权限交集。",
            "arguments": {"repo_root": str(tmp_path)},
        },
    )
    assert denied.status_code == 201, denied.text
    assert denied.json()["status"] == "failed"
    assert denied.json()["error_code"] == "subagent_tool_not_allowed"
    scope = denied.json()["audit_json"]["subagent_permission_scope"]
    assert scope["child_role"] == "reviewer"
    assert scope["ancestor_roles"] == ["planner"]
    assert "git.diff" not in scope["effective_allowed_tools"]

    allowed = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": child_run["id"],
            "tool_name": "repo.list_files",
            "risk_level": "L0",
            "idempotency_key": "subagent-parent-intersection-allowed",
            "reason": "验证父子角色共同允许的只读工具。",
            "arguments": {"workspace_root": str(tmp_path), "path": "."},
        },
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["status"] == "succeeded"
    assert (
        allowed.json()["audit_json"]["subagent_permission_scope"]
        ["effective_allowed_tools"]
        == ["repo.list_files", "repo.read_file", "repo.search_text"]
    )


def test_l3_tool_gateway_call_creates_approval_without_execution(client: TestClient) -> None:
    """L3 工具只创建审批请求，ToolCall 保持 waiting_approval。"""

    task = _task(client)
    agent_run = create_running_agent_run(task["id"], "release")
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "approval.request_remote_action",
            "risk_level": "L3",
            "idempotency_key": "approval-1",
            "reason": "演示远端动作审批拦截",
            "arguments": {
                "action": "restart-demo-service",
                "target_environment": "staging",
                "reason": "验证审批链路",
            },
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "waiting_approval"
    assert payload["approval_id"] is not None
    assert payload["finished_at"] is None

    approvals = client.get("/api/approvals", params={"status": "pending"}).json()["items"]
    assert approvals[0]["id"] == payload["approval_id"]
    assert approvals[0]["action"] == "approval.request_remote_action"


def test_idempotent_replay_reuses_call_and_argument_conflict_is_traceable(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """完全相同的重放复用终态，参数漂移返回稳定 409。"""

    task = _task(client)
    body = {
        "tool_name": "repo.read_file",
        "risk_level": "L0",
        "idempotency_key": "same-key",
        "reason": "测试幂等键",
        "arguments": {"workspace_root": str(tmp_path), "path": "README.md"},
    }
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    first = client.post(f"/api/tasks/{task['id']}/tool-gateway/call", json=body)
    assert first.status_code == 201, first.text
    replay = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json=body,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]

    (tmp_path / "OTHER.md").write_text("# other\n", encoding="utf-8")
    conflict = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            **body,
            "arguments": {
                "workspace_root": str(tmp_path),
                "path": "OTHER.md",
            },
        },
    )
    assert conflict.status_code == 409
    error = conflict.json()
    assert error["code"] == "idempotency_conflict"
    assert error["trace_id"]


def test_sensitive_path_is_recorded_as_failed_tool_call(client: TestClient, tmp_path: Path) -> None:
    """敏感文件访问被策略拒绝，并形成失败 ToolCall。"""

    task = _task(client)
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "tool_name": "repo.read_file",
            "risk_level": "L0",
            "idempotency_key": "sensitive-1",
            "reason": "验证敏感文件拒绝",
            "arguments": {"workspace_root": str(tmp_path), "path": ".env"},
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "path_sensitive_file"


def test_tool_gateway_rate_limit_is_persisted_as_failed_call(client: TestClient, tmp_path: Path) -> None:
    """超额调用必须写入失败 ToolCall 和可追溯事件。"""

    client.app.state.tool_gateway = create_default_gateway(
        max_calls=1,
        window_seconds=60,
        allowed_workspace_roots=[tmp_path],
    )
    task = _task(client)
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    base_body = {
        "tool_name": "repo.read_file",
        "risk_level": "L0",
        "reason": "验证 Tool Gateway 限流",
        "arguments": {"workspace_root": str(tmp_path), "path": "README.md"},
    }

    first = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={**base_body, "idempotency_key": "rate-limit-1"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "succeeded"

    second = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={**base_body, "idempotency_key": "rate-limit-2"},
    )
    assert second.status_code == 201, second.text
    payload = second.json()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "rate_limit_exceeded"
    assert payload["result_json"]["retry_after_seconds"] >= 1

    timeline = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    failed_events = [item for item in timeline if item["event_type"] == "ToolCallFailed"]
    assert failed_events[-1]["payload"]["error_code"] == "rate_limit_exceeded"


def test_side_effect_tool_requires_agent_run(client: TestClient, tmp_path: Path) -> None:
    """公开 API 不得在无 AgentRun 时直接执行写文件工具。"""

    task = _task(client)
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "tool_name": "repo.write_file",
            "risk_level": "L1",
            "idempotency_key": "system-write-denied",
            "reason": "验证副作用工具权限",
            "arguments": {"workspace_root": str(tmp_path), "path": "denied.txt", "content": "denied"},
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "agent_run_required"
    assert not (tmp_path / "denied.txt").exists()


def test_tool_gateway_rejects_non_running_agent_run(client: TestClient, tmp_path: Path) -> None:
    """pending/failed AgentRun 不能冒充正在执行的 Agent 调用工具。"""

    task = _task(client)
    agent_run = client.post(
        f"/api/tasks/{task['id']}/agent-runs",
        json={"agent_type": "coder", "status": "pending", "model_name": "test-model"},
    ).json()
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "repo.write_file",
            "risk_level": "L1",
            "idempotency_key": "pending-agent-denied",
            "reason": "验证 AgentRun 生命周期约束",
            "arguments": {"workspace_root": str(tmp_path), "path": "denied.txt", "content": "denied"},
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_run_not_running"
    assert not (tmp_path / "denied.txt").exists()


def test_tool_gateway_rejects_agent_call_when_task_is_paused(client: TestClient, tmp_path: Path) -> None:
    """Task 暂停后，即使 AgentRun 仍为 running 也不能继续产生副作用。"""

    task = _task(client)
    agent_run = create_running_agent_run(task["id"], "coder")
    assert client.post(f"/api/tasks/{task['id']}/pause").status_code == 200

    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "repo.write_file",
            "risk_level": "L1",
            "idempotency_key": "paused-agent-denied",
            "reason": "验证任务暂停边界",
            "arguments": {"workspace_root": str(tmp_path), "path": "denied.txt", "content": "denied"},
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "task_not_running"
    assert not (tmp_path / "denied.txt").exists()


def test_tool_gateway_rejects_workspace_outside_configured_roots(client: TestClient, tmp_path: Path) -> None:
    """调用方不能把任意本机目录声明为受控 workspace。"""

    task = _task(client)
    outside = Path.home()
    response = client.post(
        f"/api/tasks/{task['id']}/tool-gateway/call",
        json={
            "tool_name": "repo.list_files",
            "risk_level": "L0",
            "idempotency_key": "outside-workspace",
            "reason": "验证 workspace allowlist",
            "arguments": {"workspace_root": str(outside), "path": "."},
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "workspace_not_allowed"
