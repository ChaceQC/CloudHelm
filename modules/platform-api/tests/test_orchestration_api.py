"""M4 Orchestration API 黑盒与事务副作用测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from time import sleep
from urllib import error

from fastapi.testclient import TestClient

from cloudhelm_agent_runtime.agents import RequirementAgent
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.services.agent_run_lifecycle import (
    AgentRunLifecycle,
)
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


def test_expected_phase_prevents_duplicate_m4_side_effects(
    client: TestClient,
) -> None:
    """旧阶段请求只能返回冲突，不能连续推进两个 Agent 或重复写产物。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证 M4 阶段前置条件")

    started = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "actor_id": "tester",
            "expected_phase": "Created",
        },
    )
    assert started.status_code == 200, started.text

    duplicate_start = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "actor_id": "tester",
            "expected_phase": "Created",
        },
    )
    assert duplicate_start.status_code == 409
    assert duplicate_start.json()["code"] == "orchestration_phase_changed"
    assert duplicate_start.json()["detail"] == {
        "expected_phase": "Created",
        "actual_phase": "RequirementClarifying",
    }

    requirement = client.post(
        f"/api/tasks/{task['id']}/run-next",
        json={
            "actor_id": "tester",
            "expected_phase": "RequirementClarifying",
        },
    )
    assert requirement.status_code == 200, requirement.text

    duplicate_requirement = client.post(
        f"/api/tasks/{task['id']}/run-next",
        json={
            "actor_id": "tester",
            "expected_phase": "RequirementClarifying",
        },
    )
    assert duplicate_requirement.status_code == 409
    assert duplicate_requirement.json()["code"] == (
        "orchestration_phase_changed"
    )
    assert duplicate_requirement.json()["detail"]["actual_phase"] == (
        "Designing"
    )

    requirements = client.get(
        f"/api/tasks/{task['id']}/requirements"
    ).json()["items"]
    agent_runs = client.get(
        f"/api/tasks/{task['id']}/agent-runs"
    ).json()["items"]
    assert len(requirements) == 1
    assert [
        run for run in agent_runs if run["agent_type"] == "requirement"
    ][0]["status"] == "succeeded"
    assert sum(
        run["agent_type"] == "requirement"
        for run in agent_runs
    ) == 1


def test_concurrent_run_next_locks_task_before_starting_agent(
    client: TestClient,
    monkeypatch,
) -> None:
    """并发相同阶段请求只有一个能创建 AgentRun，另一个等待后返回 409。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证 M4 并发步骤抢占")
    assert client.post(
        f"/api/tasks/{task['id']}/start",
        json={"expected_phase": "Created"},
    ).status_code == 200

    first_started = Event()
    release_first = Event()
    calls_lock = Lock()
    start_calls = 0
    original_start = AgentRunLifecycle.start

    def blocking_start(
        lifecycle,
        task_model,
        agent_type,
        *,
        workflow_step=None,
    ):
        nonlocal start_calls
        agent_run = original_start(
            lifecycle,
            task_model,
            agent_type,
            workflow_step=workflow_step,
        )
        if agent_type == "requirement" and workflow_step is None:
            with calls_lock:
                start_calls += 1
                call_number = start_calls
            if call_number == 1:
                first_started.set()
                assert release_first.wait(timeout=10)
        return agent_run

    monkeypatch.setattr(AgentRunLifecycle, "start", blocking_start)
    payload = {
        "actor_id": "tester",
        "expected_phase": "RequirementClarifying",
    }

    with (
        TestClient(create_app()) as first_client,
        TestClient(create_app()) as second_client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first_future = executor.submit(
            first_client.post,
            f"/api/tasks/{task['id']}/run-next",
            json=payload,
        )
        assert first_started.wait(timeout=10)
        second_future = executor.submit(
            second_client.post,
            f"/api/tasks/{task['id']}/run-next",
            json=payload,
        )
        sleep(0.2)
        with calls_lock:
            assert start_calls == 1
        assert second_future.done() is False
        release_first.set()
        first_response = first_future.result(timeout=15)
        second_response = second_future.result(timeout=15)

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 409, second_response.text
    assert second_response.json()["code"] == "orchestration_phase_changed"
    with calls_lock:
        assert start_calls == 1

    agent_runs = client.get(
        f"/api/tasks/{task['id']}/agent-runs"
    ).json()["items"]
    assert sum(
        run["agent_type"] == "requirement"
        for run in agent_runs
    ) == 1


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


def test_local_provider_rejects_unsupported_design_without_partial_product(
    client: TestClient,
) -> None:
    """无受控 recipe 的本地需求必须明确暂停，不能落入固定技术设计。"""

    project = create_project(client)
    task_response = client.post(
        "/api/tasks",
        json={
            "project_id": project["id"],
            "title": "实现天气 Platform API",
            "description": (
                "为外部天气应用实现 platform API，返回东京未来三天的天气"
                "和温度范围。"
            ),
            "source_type": "manual",
            "risk_level": "L1",
            "created_by": "tester",
        },
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200

    architect = client.post(f"/api/tasks/{task['id']}/run-next")

    assert architect.status_code == 409
    assert architect.json()["code"] == "unsupported_local_recipe"
    task_state = client.get(f"/api/tasks/{task['id']}").json()
    assert task_state["status"] == "paused"
    assert task_state["current_phase"] == "Designing"
    designs = client.get(
        f"/api/tasks/{task['id']}/technical-designs"
    ).json()["items"]
    assert designs == []
    agent_run = client.get(
        f"/api/tasks/{task['id']}/agent-runs"
    ).json()["items"][0]
    assert agent_run["agent_type"] == "architect"
    assert agent_run["status"] == "failed"
    assert agent_run["error_code"] == "unsupported_local_recipe"


def test_plan_approval_preserves_l4_planner_risk(
    client: TestClient,
) -> None:
    """计划审批不得把 L4 设计和 Planner 风险降级为 L1。"""

    project = create_project(client)
    task_response = client.post(
        "/api/tasks",
        json={
            "project_id": project["id"],
            "title": "验证 CloudHelm M4 高风险编排",
            "description": (
                "验证 CloudHelm M4 编排的高风险权限、数据库迁移和审批边界。"
            ),
            "source_type": "manual",
            "risk_level": "L4",
            "created_by": "tester",
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = task_response.json()["id"]
    assert client.post(f"/api/tasks/{task_id}/start").status_code == 200
    assert client.post(f"/api/tasks/{task_id}/run-next").status_code == 200
    design_step = client.post(f"/api/tasks/{task_id}/run-next")
    assert design_step.status_code == 200, design_step.text
    assert design_step.json()["approval"]["risk_level"] == "L4"
    assert client.post(
        f"/api/approvals/{design_step.json()['approval']['id']}/approve",
        json={"actor_id": "tester"},
    ).status_code == 200

    plan_step = client.post(f"/api/tasks/{task_id}/run-next")

    assert plan_step.status_code == 200, plan_step.text
    assert plan_step.json()["approval"]["action"] == "approve_development_plan"
    assert plan_step.json()["approval"]["risk_level"] == "L4"


def test_requirement_risk_elevation_reaches_architect_approval(
    client: TestClient,
    monkeypatch,
) -> None:
    """Requirement 新识别的高风险必须写回 Task 并约束后续设计审批。"""

    project = create_project(client)
    task = create_task(
        client,
        project["id"],
        title="验证 CloudHelm M4 需求风险传播",
    )
    original_run = RequirementAgent.run

    def elevated_requirement(agent, payload, *, conversation):
        output = original_run(
            agent,
            payload,
            conversation=conversation,
        )
        return output.model_copy(
            update={"risk_level": RiskLevel.L3}
        )

    monkeypatch.setattr(RequirementAgent, "run", elevated_requirement)
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200

    requirement_step = client.post(
        f"/api/tasks/{task['id']}/run-next"
    )
    assert requirement_step.status_code == 200, requirement_step.text
    assert requirement_step.json()["task"]["risk_level"] == "L3"

    design_step = client.post(f"/api/tasks/{task['id']}/run-next")

    assert design_step.status_code == 200, design_step.text
    assert design_step.json()["technical_design"]["risk_level"] == "L3"
    assert design_step.json()["approval"]["risk_level"] == "L3"


def test_transient_llm_request_failure_pauses_task_after_bounded_retries(
    client: TestClient,
    monkeypatch,
) -> None:
    """外部模型瞬时失败耗尽重试后应暂停任务，保留可恢复编排阶段。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="验证外部模型失败恢复")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    attempts = 0

    def fail_request(http_request, timeout):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        raise error.URLError("temporary")

    monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLOUDHELM_LLM_API_BASE", "https://api.example.test")
    monkeypatch.setenv("CLOUDHELM_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDHELM_LLM_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("CLOUDHELM_LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("CLOUDHELM_LLM_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fail_request)
    get_settings.cache_clear()
    try:
        response = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"})
        assert response.status_code == 503
        assert response.json()["code"] == "agent_provider_request_failed"
    finally:
        monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "local_structured")
        get_settings.cache_clear()

    assert attempts == 2
    task_body = client.get(f"/api/tasks/{task['id']}").json()
    assert task_body["status"] == "paused"
    assert task_body["current_phase"] == "RequirementClarifying"

    agent_run = client.get(f"/api/tasks/{task['id']}/agent-runs").json()["items"][0]
    assert agent_run["status"] == "failed"
    assert agent_run["error_code"] == "agent_provider_request_failed"

    failed_event = next(
        event
        for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
        if event["event_type"] == "AgentRunFailed"
    )
    assert failed_event["payload"]["recoverable"] is True


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
