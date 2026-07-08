"""M4 Orchestration API 黑盒与事务副作用测试。"""

from fastapi.testclient import TestClient

from cloudhelm_platform_api.core.config import get_settings
from conftest import create_project, create_task


def test_m4_orchestration_generates_requirement_design_plan_and_events(client: TestClient) -> None:
    """覆盖 Created -> Requirement -> DesignApproval -> Planning -> DevelopmentPlan 主路径。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="实现 M4 编排闭环")

    start = client.post(f"/api/tasks/{task['id']}/start", json={"actor_id": "tester"})
    assert start.status_code == 200, start.text
    assert start.json()["task"]["current_phase"] == "RequirementClarifying"

    requirement_step = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
    assert requirement_step.status_code == 200, requirement_step.text
    requirement_body = requirement_step.json()
    assert requirement_body["task"]["current_phase"] == "Designing"
    assert requirement_body["requirement"]["status"] == "approved"
    assert requirement_body["agent_run"]["structured_output_type"] == "requirement_agent_output"

    design_step = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
    assert design_step.status_code == 200, design_step.text
    design_body = design_step.json()
    assert design_body["task"]["current_phase"] == "WaitingDesignApproval"
    assert design_body["task"]["status"] == "waiting_approval"
    assert design_body["technical_design"]["risk_level"] == "L2"
    assert design_body["approval"]["action"] == "approve_technical_design"

    approve = client.post(
        f"/api/technical-designs/{design_body['technical_design']['id']}/approve",
        json={"actor_id": "architect", "reason": "同意 M4 设计"},
    )
    assert approve.status_code == 200, approve.text

    resume = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
    assert resume.status_code == 200, resume.text
    assert resume.json()["task"]["current_phase"] == "Planning"

    plan_step = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
    assert plan_step.status_code == 200, plan_step.text
    plan_body = plan_step.json()
    assert plan_body["development_plan"]["status"] == "ready_for_review"
    assert plan_body["development_plan"]["steps_json"][0]["id"] == "STEP-001"
    assert plan_body["approval"]["action"] == "approve_development_plan"

    plans = client.get(f"/api/tasks/{task['id']}/development-plans")
    assert plans.status_code == 200
    assert plans.json()["items"][0]["id"] == plan_body["development_plan"]["id"]

    timeline = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    event_types = [event["event_type"] for event in timeline]
    assert "TaskPhaseChanged" in event_types
    assert "AgentRunStarted" in event_types
    assert "AgentRunCompleted" in event_types
    assert "RequirementSpecCreated" in event_types
    assert "TechnicalDesignCreated" in event_types
    assert "DevelopmentPlanCreated" in event_types
    assert event_types.count("ApprovalRequested") >= 2


def test_run_next_requires_start_and_returns_traceable_conflict(client: TestClient) -> None:
    """未 start 时 run-next 应返回稳定冲突错误和 trace_id。"""

    project = create_project(client)
    task = create_task(client, project["id"])

    response = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "orchestration_not_started"
    assert body["trace_id"]


def test_missing_llm_config_records_failed_agent_run(client: TestClient, monkeypatch) -> None:
    """切换外部模型 provider 但缺少配置时，应写失败事件而不是固定输出。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    start = client.post(f"/api/tasks/{task['id']}/start", json={"actor_id": "tester"})
    assert start.status_code == 200

    monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "openai_compatible")
    monkeypatch.delenv("CLOUDHELM_LLM_API_BASE", raising=False)
    monkeypatch.delenv("CLOUDHELM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDHELM_LLM_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        response = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
        assert response.status_code == 409
        assert response.json()["code"] == "missing_agent_provider_config"
    finally:
        monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "local_structured")
        get_settings.cache_clear()

    agent_runs = client.get(f"/api/tasks/{task['id']}/agent-runs").json()["items"]
    assert agent_runs[0]["status"] == "failed"
    assert agent_runs[0]["error_code"] == "missing_agent_provider_config"

    events = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    assert "AgentRunFailed" in [event["event_type"] for event in events]
