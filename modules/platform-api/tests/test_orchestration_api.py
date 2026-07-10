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
    design_approval = client.get(f"/api/approvals/{design_body['approval']['id']}")
    assert design_approval.status_code == 200
    assert design_approval.json()["status"] == "approved"

    plan_step = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
    assert plan_step.status_code == 200, plan_step.text
    plan_body = plan_step.json()
    assert plan_body["development_plan"]["status"] == "ready_for_review"
    assert plan_body["development_plan"]["steps_json"][0]["id"] == "STEP-001"
    assert plan_body["approval"]["action"] == "approve_development_plan"

    approve_plan = client.post(
        f"/api/approvals/{plan_body['approval']['id']}/approve",
        json={"actor_id": "reviewer", "reason": "计划边界清晰"},
    )
    assert approve_plan.status_code == 200, approve_plan.text
    assert client.get(f"/api/development-plans/{plan_body['development_plan']['id']}").json()["status"] == "approved"
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "running"

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
    assert "DevelopmentPlanApproved" in event_types
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


def test_rejected_plan_is_regenerated_instead_of_reusing_stale_plan(client: TestClient) -> None:
    """计划被拒绝后，run-next 必须为当前设计生成新计划。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证计划返工")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    design_step = client.post(f"/api/tasks/{task['id']}/run-next").json()
    assert client.post(f"/api/approvals/{design_step['approval']['id']}/approve").status_code == 200
    first_plan_step = client.post(f"/api/tasks/{task['id']}/run-next").json()

    reject = client.post(
        f"/api/approvals/{first_plan_step['approval']['id']}/reject",
        json={"actor_id": "reviewer", "reason": "需要调整任务拆分"},
    )
    assert reject.status_code == 200, reject.text
    first_plan_id = first_plan_step["development_plan"]["id"]
    assert client.get(f"/api/development-plans/{first_plan_id}").json()["status"] == "changes_requested"

    state = client.get(f"/api/tasks/{task['id']}/orchestration").json()
    assert state["plan_exists"] is False
    assert state["next_action"] == "run_planner"

    regenerated = client.post(f"/api/tasks/{task['id']}/run-next")
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["development_plan"]["id"] != first_plan_id
    assert regenerated.json()["development_plan"]["status"] == "ready_for_review"
    assert regenerated.json()["development_plan"]["version"] == 2


def test_design_revision_invalidates_old_plan_and_approval(client: TestClient) -> None:
    """技术设计返工后，旧开发计划及其待审批记录必须失效。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证设计返工")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    requirement = client.post(f"/api/tasks/{task['id']}/run-next").json()["requirement"]
    design_step = client.post(f"/api/tasks/{task['id']}/run-next").json()
    assert client.post(f"/api/approvals/{design_step['approval']['id']}/approve").status_code == 200
    plan_step = client.post(f"/api/tasks/{task['id']}/run-next").json()

    changes = client.post(
        f"/api/technical-designs/{design_step['technical_design']['id']}/request-changes",
        json={"actor_id": "architect", "reason": "补充事务边界"},
    )
    assert changes.status_code == 200, changes.text
    assert client.get(f"/api/development-plans/{plan_step['development_plan']['id']}").json()["status"] == "changes_requested"
    assert client.get(f"/api/approvals/{plan_step['approval']['id']}").json()["status"] == "rejected"

    revised_design = client.post(f"/api/tasks/{task['id']}/run-next")
    assert revised_design.status_code == 200, revised_design.text
    assert revised_design.json()["technical_design"]["requirement_spec_id"] == requirement["id"]
    assert revised_design.json()["technical_design"]["id"] != design_step["technical_design"]["id"]
    assert revised_design.json()["technical_design"]["version"] == 2


def test_requirement_revision_invalidates_downstream_design_and_plan(client: TestClient) -> None:
    """需求返工后，旧设计、旧计划和计划审批都不能继续使用。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证需求返工")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    requirement = client.post(f"/api/tasks/{task['id']}/run-next").json()["requirement"]
    design_step = client.post(f"/api/tasks/{task['id']}/run-next").json()
    assert client.post(f"/api/approvals/{design_step['approval']['id']}/approve").status_code == 200
    plan_step = client.post(f"/api/tasks/{task['id']}/run-next").json()

    changes = client.post(
        f"/api/requirements/{requirement['id']}/request-changes",
        json={"actor_id": "reviewer", "reason": "补充新的验收标准"},
    )
    assert changes.status_code == 200, changes.text
    assert client.get(f"/api/technical-designs/{design_step['technical_design']['id']}").json()["status"] == "changes_requested"
    assert client.get(f"/api/development-plans/{plan_step['development_plan']['id']}").json()["status"] == "changes_requested"
    assert client.get(f"/api/approvals/{plan_step['approval']['id']}").json()["status"] == "rejected"

    task_state = client.get(f"/api/tasks/{task['id']}").json()
    assert task_state["status"] == "running"
    assert task_state["current_phase"] == "RequirementClarifying"


def test_resume_after_plan_decision_while_paused_restores_running(client: TestClient) -> None:
    """等待计划审批时暂停，审批完成后恢复应进入 running 而非残留 waiting_approval。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证暂停审批恢复")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    design_step = client.post(f"/api/tasks/{task['id']}/run-next").json()
    assert client.post(f"/api/approvals/{design_step['approval']['id']}/approve").status_code == 200
    plan_step = client.post(f"/api/tasks/{task['id']}/run-next").json()

    assert client.post(f"/api/tasks/{task['id']}/pause").json()["status"] == "paused"
    assert client.post(f"/api/approvals/{plan_step['approval']['id']}/approve").status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "paused"

    resumed = client.post(f"/api/tasks/{task['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"


def test_paused_task_cannot_bypass_resume_to_start_orchestration(client: TestClient) -> None:
    """暂停任务只能先通过 Task API 恢复，不能直接启动编排。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="暂停编排")
    assert client.post(f"/api/tasks/{task['id']}/pause").status_code == 200

    response = client.post(f"/api/tasks/{task['id']}/start")
    assert response.status_code == 409
    assert response.json()["code"] == "task_paused"
