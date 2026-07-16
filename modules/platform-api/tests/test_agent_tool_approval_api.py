"""AgentRun、ToolCall 与 Approval API 测试。"""

from fastapi.testclient import TestClient

from conftest import create_project, create_task


def test_agent_run_tool_call_and_approval_records_are_queryable(client: TestClient) -> None:
    """验证 M2 内部联调创建接口写入真实数据库并可查询。"""

    project = create_project(client)
    task = create_task(client, project["id"])

    agent_run_response = client.post(
        f"/api/tasks/{task['id']}/agent-runs",
        json={"agent_type": "RequirementAgent", "status": "succeeded", "model_name": "demo-model"},
    )
    assert agent_run_response.status_code == 201, agent_run_response.text
    agent_run = agent_run_response.json()

    approval_response = client.post(
        f"/api/tasks/{task['id']}/approvals",
        json={
            "action": "run_l3_tool",
            "risk_level": "L3",
            "reason": "验证审批记录。",
            "requested_by_agent_run_id": agent_run["id"],
        },
    )
    assert approval_response.status_code == 201, approval_response.text
    approval = approval_response.json()
    assert approval["status"] == "pending"

    tool_call_response = client.post(
        f"/api/tasks/{task['id']}/tool-calls",
        json={
            "agent_run_id": agent_run["id"],
            "tool_name": "repo.read_file",
            "risk_level": "L1",
            "arguments_json": {"path": "README.md", "secret": "masked-by-summary"},
            "arguments_summary": "secret=masked-by-summary",
            "result_summary": "token=sensitive-result-token",
            "status": "succeeded",
            "approval_id": approval["id"],
        },
    )
    assert tool_call_response.status_code == 201, tool_call_response.text
    tool_call = tool_call_response.json()
    assert tool_call["tool_name"] == "repo.read_file"
    assert tool_call["arguments_summary"] == "keys=[path, secret]"
    assert "masked-by-summary" not in tool_call["arguments_summary"]
    assert tool_call["result_summary"] == "token=<redacted>"
    assert "sensitive-result-token" not in tool_call_response.text
    assert tool_call["audit_json"]["source"] == "internal_record_api"
    assert tool_call["audit_json"]["arguments_hash"].startswith("sha256:")

    assert client.get(f"/api/agent-runs/{agent_run['id']}").json()["id"] == agent_run["id"]
    persisted_tool_call = client.get(f"/api/tool-calls/{tool_call['id']}")
    assert persisted_tool_call.json()["id"] == tool_call["id"]
    assert persisted_tool_call.json()["result_summary"] == "token=<redacted>"
    assert "sensitive-result-token" not in persisted_tool_call.text
    assert client.get("/api/approvals").json()["items"][0]["id"] == approval["id"]

    approve = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"actor_id": "operator", "reason": "同意执行"},
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    rejected = client.post(
        f"/api/tasks/{task['id']}/approvals",
        json={"action": "deploy", "risk_level": "L4", "reason": "验证拒绝分支。"},
    ).json()
    reject = client.post(
        f"/api/approvals/{rejected['id']}/reject",
        json={"actor_id": "operator", "reason": "风险过高"},
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    event_types = [event["event_type"] for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]]
    assert "AgentRunRecorded" in event_types
    assert "ToolCallRecorded" in event_types
    assert "ApprovalApproved" in event_types
    assert "ApprovalRejected" in event_types


def test_internal_tool_call_api_rejects_caller_supplied_audit_fields(client: TestClient) -> None:
    """内部记录接口也不得允许调用方伪造服务端审计字段。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    response = client.post(
        f"/api/tasks/{task['id']}/tool-calls",
        json={
            "tool_name": "repo.read_file",
            "risk_level": "L1",
            "arguments_json": {"path": "README.md"},
            "audit_json": {"arguments_hash": "forged", "status": "succeeded"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_generic_approval_api_rejects_release_candidate_action(
    client: TestClient,
) -> None:
    """第一道候选发布审批只能由服务端 Candidate 事务创建。"""

    project = create_project(client)
    task = create_task(client, project["id"])

    response = client.post(
        f"/api/tasks/{task['id']}/approvals",
        json={
            "action": "approve_release_candidate",
            "risk_level": "L2",
            "reason": "尝试绕过 Candidate 资源绑定。",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "approval_action_reserved"
    approvals = client.get(
        "/api/approvals",
        params={"task_id": task["id"]},
    ).json()["items"]
    assert approvals == []


def test_internal_agent_run_api_cannot_forge_running_execution(client: TestClient) -> None:
    """running AgentRun 只能由 Orchestrator 创建，联调 API 不得提升工具权限。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    response = client.post(
        f"/api/tasks/{task['id']}/agent-runs",
        json={"agent_type": "coder", "status": "running", "model_name": "forged"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_run_running_reserved"
