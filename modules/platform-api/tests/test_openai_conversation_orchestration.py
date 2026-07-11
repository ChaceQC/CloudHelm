"""OpenAI-compatible 三阶段同会话请求体与持久化白盒集成测试。"""

from copy import deepcopy
import json
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from conftest import create_project, create_task


def _without_cache_breakpoint(value):
    """移除不参与模型 token 的显式 cache breakpoint 传输元数据。"""

    normalized = deepcopy(value)

    def visit(node):
        if isinstance(node, dict):
            node.pop("prompt_cache_breakpoint", None)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(normalized)
    return normalized


class FakeResponsesSse:
    """发送一个包含 encrypted reasoning 和最终 JSON 的完成流。"""

    def __init__(self, response_payload: dict) -> None:
        self.response_payload = response_payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def __iter__(self):
        event = {
            "type": "response.completed",
            "response": self.response_payload,
            "sequence_number": 1,
        }
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n".encode("utf-8")
        yield b"\n"


def test_three_agent_roles_replay_one_root_conversation_prefix(
    client: TestClient,
    monkeypatch,
) -> None:
    """三个 API 请求必须共享 key/header，并逐轮严格扩展完整 input prefix。"""

    captured_bodies: list[dict] = []
    captured_headers: list[dict[str, str]] = []
    outputs = [
        {
            "summary": "已规格化需求。",
            "raw_input": "实现任务时间线。",
            "user_story": "作为用户，我希望查看任务时间线，以便追踪执行状态。",
            "constraints": [
                {
                    "type": "testing",
                    "value": "必须覆盖黑盒和白盒测试。",
                    "required": True,
                }
            ],
            "acceptance_criteria": [
                {
                    "id": "AC-001",
                    "description": "API 返回可分页任务时间线。",
                    "verification": "pytest",
                    "status": "pending",
                }
            ],
            "risk_level": "L2",
        },
        {
            "summary": "已完成技术设计。",
            "content_markdown": "# 任务时间线设计\n\n覆盖 API、数据库、事件和测试。",
            "openapi_json": {
                "openapi": "3.1.0",
                "info": {"title": "Timeline", "version": "0.4.3"},
                "paths": {},
            },
            "db_schema_json": {
                "tables": [{"name": "event_logs", "purpose": "任务事件"}]
            },
            "mermaid_diagram": "flowchart LR\n  Task --> EventLog",
            "risk_level": "L2",
            "risks": ["数据库与审批事件需保持同一事务。"],
            "approval_recommended": True,
        },
        {
            "summary": "已生成开发计划。",
            "steps": [
                {
                    "id": "STEP-001",
                    "title": "同步契约",
                    "description": "更新 schema、OpenAPI 和 migration。",
                    "agent": "architect",
                    "expected_artifact": "contracts",
                    "depends_on": [],
                    "status": "pending",
                },
                {
                    "id": "STEP-002",
                    "title": "实现并测试",
                    "description": "实现 API、事件和黑白盒测试。",
                    "agent": "coder",
                    "expected_artifact": "verified_patch",
                    "depends_on": ["STEP-001"],
                    "status": "pending",
                },
            ],
            "risks": [
                {
                    "id": "RISK-001",
                    "description": "缓存或事件数据可能不一致。",
                    "mitigation": "使用真实 usage 和同一事务验证。",
                    "risk_level": "L2",
                }
            ],
            "status": "ready_for_review",
            "risk_level": "L2",
        },
    ]

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        index = len(captured_bodies)
        body = json.loads(http_request.data.decode("utf-8"))
        captured_bodies.append(body)
        captured_headers.append(
            {
                name.lower(): value
                for name, value in http_request.header_items()
            }
        )
        output = outputs[index]
        return FakeResponsesSse(
            {
                "id": f"resp_{index + 1}",
                "status": "completed",
                "usage": {
                    "input_tokens": [2000, 5000, 9000][index],
                    "input_tokens_details": {
                        "cached_tokens": [0, 2048, 4096][index]
                    },
                    "output_tokens": 300,
                },
                "output": [
                    {
                        "id": f"rs_{index + 1}",
                        "type": "reasoning",
                        "summary": [],
                        "encrypted_content": f"encrypted-{index + 1}",
                    },
                    {
                        "id": f"msg_{index + 1}",
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(output, ensure_ascii=False),
                            }
                        ],
                    },
                ],
            }
        )

    monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLOUDHELM_LLM_API_BASE", "https://api.example.test/v1")
    monkeypatch.setenv("CLOUDHELM_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDHELM_LLM_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("CLOUDHELM_LLM_REASONING_EFFORT", "xhigh")
    monkeypatch.setattr(
        "cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen",
        fake_urlopen,
    )
    get_settings.cache_clear()
    try:
        project = create_project(client, "外部模型会话契约项目")
        task = create_task(client, project["id"], title="实现任务时间线")
        assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
        assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
        design_step = client.post(f"/api/tasks/{task['id']}/run-next")
        assert design_step.status_code == 200, design_step.text
        assert client.post(
            f"/api/technical-designs/{design_step.json()['technical_design']['id']}/approve",
            json={"actor_id": "architect", "reason": "同意设计"},
        ).status_code == 200
        plan_step = client.post(f"/api/tasks/{task['id']}/run-next")
        assert plan_step.status_code == 200, plan_step.text
        assert client.post(
            f"/api/approvals/{plan_step.json()['approval']['id']}/approve",
            json={"actor_id": "reviewer", "reason": "同意计划"},
        ).status_code == 200
    finally:
        monkeypatch.setenv("CLOUDHELM_AGENT_PROVIDER", "local_structured")
        get_settings.cache_clear()

    assert len(captured_bodies) == 3
    first_input = captured_bodies[0]["input"]
    second_input = captured_bodies[1]["input"]
    third_input = captured_bodies[2]["input"]
    assert _without_cache_breakpoint(second_input[: len(first_input)]) == (
        _without_cache_breakpoint(first_input)
    )
    assert _without_cache_breakpoint(third_input[: len(second_input)]) == (
        _without_cache_breakpoint(second_input)
    )
    assert "encrypted-1" in json.dumps(second_input, ensure_ascii=False)
    assert "encrypted-2" in json.dumps(third_input, ensure_ascii=False)
    assert "<approval_context>" in json.dumps(third_input, ensure_ascii=False)
    assert captured_bodies[0]["text"] == captured_bodies[1]["text"]
    assert captured_bodies[1]["text"] == captured_bodies[2]["text"]
    assert all(
        body["text"]["format"]["name"] == "cloudhelm_agent_output_v1"
        for body in captured_bodies
    )
    assert all(
        json.dumps(body["input"], ensure_ascii=False).count(
            '"prompt_cache_breakpoint"'
        )
        == 0
        for body in captured_bodies
    )
    assert all("prompt_cache_options" not in body for body in captured_bodies)

    cache_keys = {body["prompt_cache_key"] for body in captured_bodies}
    thread_ids = {headers["thread-id"] for headers in captured_headers}
    client_request_ids = {
        headers["x-client-request-id"]
        for headers in captured_headers
    }
    assert len(cache_keys) == 1
    assert len(thread_ids) == 1
    assert client_request_ids == thread_ids
    assert all(
        body["include"] == ["reasoning.encrypted_content"]
        for body in captured_bodies
    )
    assert all(
        body["reasoning"]
        == {"effort": "xhigh", "summary": "auto", "context": "all_turns"}
        for body in captured_bodies
    )

    runs = client.get(f"/api/tasks/{task['id']}/agent-runs").json()["items"]
    ordered_runs = sorted(runs, key=lambda item: item["conversation_turn"])
    assert [run["conversation_turn"] for run in ordered_runs] == [1, 2, 3]
    assert [run["cached_input_tokens"] for run in ordered_runs] == [
        0,
        2048,
        4096,
    ]
    assert [
        run["provider_requests"][0]["cached_input_tokens"]
        for run in ordered_runs
    ] == [0, 2048, 4096]
    assert all(run["provider_request_count"] == 1 for run in ordered_runs)
    assert all(len(run["provider_requests"]) == 1 for run in ordered_runs)
    assert len({run["conversation_id"] for run in runs}) == 1

    with Session(get_engine()) as session:
        root = session.scalar(
            select(AgentConversation).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "root",
            )
        )
        assert root is not None
        assert root.turn_count == 3
        serialized = json.dumps(root.items_json, ensure_ascii=False)
        assert _without_cache_breakpoint(root.items_json) == root.items_json
        for index in (1, 2, 3):
            assert f"encrypted-{index}" in serialized
