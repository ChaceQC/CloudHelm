"""真实外部模型 M4 编排集成测试。

默认测试回归不访问计费端点。只有显式设置
`CLOUDHELM_RUN_EXTERNAL_LLM_TESTS=1` 并通过环境变量注入 API Base、Key、
模型与推理强度时，才执行 Requirement、Architect、Planner 三次真实调用。
"""

import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from conftest import create_project

pytestmark = pytest.mark.skipif(
    os.environ.get("CLOUDHELM_RUN_EXTERNAL_LLM_TESTS") != "1",
    reason="需要显式启用真实外部模型测试。",
)


def test_real_gpt_5_6_sol_xhigh_completes_m4_orchestration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 `gpt-5.6-sol` + `xhigh` 应完成三类 Agent 与数据库事件闭环。"""

    api_base = os.environ.get("CLOUDHELM_LLM_API_BASE")
    api_key = os.environ.get("CLOUDHELM_LLM_API_KEY")
    if not api_base or not api_key:
        pytest.skip("未注入真实 CLOUDHELM_LLM_API_BASE/CLOUDHELM_LLM_API_KEY。")

    model = os.environ.get("CLOUDHELM_LLM_MODEL", "gpt-5.6-sol")
    effort = os.environ.get("CLOUDHELM_LLM_REASONING_EFFORT", "xhigh")
    assert model == "gpt-5.6-sol"
    assert effort == "xhigh"

    monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLOUDHELM_LLM_API_BASE", api_base)
    monkeypatch.setenv("CLOUDHELM_LLM_API_KEY", api_key)
    monkeypatch.setenv("CLOUDHELM_LLM_MODEL", model)
    monkeypatch.setenv("CLOUDHELM_LLM_API_MODE", "responses")
    monkeypatch.setenv("CLOUDHELM_LLM_REASONING_EFFORT", effort)
    monkeypatch.setenv("CLOUDHELM_LLM_MAX_OUTPUT_TOKENS", "32768")
    monkeypatch.setenv("CLOUDHELM_LLM_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("CLOUDHELM_LLM_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CLOUDHELM_LLM_RETRY_BACKOFF_SECONDS", "1")
    monkeypatch.setenv("CLOUDHELM_LLM_USER_AGENT", "codex_cli_rs/0.0.0 (CloudHelm external pytest)")
    monkeypatch.setenv("CLOUDHELM_LLM_ORIGINATOR", "codex_cli_rs")
    get_settings.cache_clear()

    try:
        project = create_project(client, "真实外部模型集成项目")
        task_response = client.post(
            "/api/tasks",
            json={
                "project_id": project["id"],
                "title": "实现带审计事件的任务时间线",
                "description": (
                    "为 CloudHelm 控制台实现任务 Agent 时间线。后端需要新增可分页 API、"
                    "数据库字段和 Alembic 迁移；审批动作必须写入审计事件，并补充黑盒、"
                    "白盒和响应式控制台测试。"
                ),
                "source_type": "manual",
                "risk_level": "L2",
                "created_by": "external-integration-test",
            },
        )
        assert task_response.status_code == 201, task_response.text
        task = task_response.json()

        start = client.post(f"/api/tasks/{task['id']}/start", json={"actor_id": "external-tester"})
        assert start.status_code == 200, start.text

        requirement_step = client.post(
            f"/api/tasks/{task['id']}/run-next",
            json={"actor_id": "external-tester"},
        )
        assert requirement_step.status_code == 200, requirement_step.text
        assert requirement_step.json()["requirement"]["status"] == "approved"

        design_step = client.post(
            f"/api/tasks/{task['id']}/run-next",
            json={"actor_id": "external-tester"},
        )
        assert design_step.status_code == 200, design_step.text
        design_body = design_step.json()
        assert design_body["technical_design"]["created_by_agent_run_id"]
        if design_body["technical_design"]["status"] == "draft":
            approve_design = client.post(
                f"/api/technical-designs/{design_body['technical_design']['id']}/approve",
                json={"actor_id": "external-architect", "reason": "真实模型集成测试批准设计"},
            )
            assert approve_design.status_code == 200, approve_design.text

        plan_step = client.post(
            f"/api/tasks/{task['id']}/run-next",
            json={"actor_id": "external-tester"},
        )
        assert plan_step.status_code == 200, plan_step.text
        plan_body = plan_step.json()
        assert plan_body["development_plan"]["status"] == "ready_for_review"
        assert plan_body["development_plan"]["steps_json"]

        approve_plan = client.post(
            f"/api/approvals/{plan_body['approval']['id']}/approve",
            json={"actor_id": "external-reviewer", "reason": "真实模型集成测试批准计划"},
        )
        assert approve_plan.status_code == 200, approve_plan.text

        agent_runs = client.get(f"/api/tasks/{task['id']}/agent-runs").json()["items"]
        ordered_runs = sorted(
            agent_runs,
            key=lambda run: run["conversation_turn"],
        )
        assert [run["agent_type"] for run in ordered_runs] == [
            "requirement",
            "architect",
            "planner",
        ]
        assert [run["conversation_turn"] for run in ordered_runs] == [1, 2, 3]
        assert len({run["conversation_id"] for run in ordered_runs}) == 1
        assert len({run["prompt_cache_key"] for run in ordered_runs}) == 1
        assert all(run["status"] == "succeeded" for run in ordered_runs)
        assert all(run["model_name"] == "gpt-5.6-sol" for run in ordered_runs)
        assert all(run["input_tokens"] > 0 for run in ordered_runs)
        assert all(run["output_tokens"] > 0 for run in ordered_runs)
        for run in ordered_runs:
            requests = run["provider_requests"]
            assert len(requests) == run["provider_request_count"]
            assert sum(item["input_tokens"] for item in requests) == run["input_tokens"]
            assert (
                sum(item["cached_input_tokens"] for item in requests)
                == run["cached_input_tokens"]
            )
            assert sum(item["output_tokens"] for item in requests) == run["output_tokens"]
            assert all(
                item["cache_hit"] == (item["cached_input_tokens"] > 0)
                for item in requests
            )
        final_requests = [run["provider_requests"][-1] for run in ordered_runs]
        input_tokens = [item["input_tokens"] for item in final_requests]
        cached_tokens = [
            item["cached_input_tokens"]
            for item in final_requests
        ]
        assert input_tokens[0] < input_tokens[1] < input_tokens[2], input_tokens
        assert cached_tokens[0] == 0, cached_tokens
        assert cached_tokens[1] > 0, cached_tokens
        assert cached_tokens[2] > cached_tokens[1], cached_tokens
        assert all(run["provider_response_id"] for run in ordered_runs)

        with Session(get_engine()) as session:
            conversations = list(
                session.scalars(
                    select(AgentConversation).where(
                        AgentConversation.task_id == UUID(task["id"])
                    )
                )
            )
            assert len(conversations) == 1
            root = conversations[0]
            assert root.source_type == "root"
            assert root.parent_conversation_id is None
            assert root.turn_count == 3
            assert str(root.id) == ordered_runs[0]["conversation_id"]
            assert root.prompt_cache_key == ordered_runs[0]["prompt_cache_key"]
            assert root.last_response_id == ordered_runs[-1]["provider_response_id"]

        timeline = client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
        event_types = [event["event_type"] for event in timeline]
        assert event_types.count("AgentRunCompleted") == 3
        assert "RequirementSpecCreated" in event_types
        assert "TechnicalDesignCreated" in event_types
        assert "DevelopmentPlanCreated" in event_types
        assert "DevelopmentPlanApproved" in event_types
        completed_events = [event for event in timeline if event["event_type"] == "AgentRunCompleted"]
        assert all(event["payload"]["cache"]["prompt_cache_key"].startswith("cloudhelm:") for event in completed_events)
        assert all(event["payload"]["input_tokens"] > 0 for event in completed_events)
        assert all(event["payload"]["cache"]["requests"] for event in completed_events)
    finally:
        monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "local_structured")
        get_settings.cache_clear()
