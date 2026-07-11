"""Agent Runtime 结构化输出白盒测试。"""

from copy import deepcopy
import json
from urllib import error
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cloudhelm_agent_runtime.agents import ArchitectAgent, PlannerAgent, RequirementAgent
from cloudhelm_agent_runtime.providers import (
    AgentProviderResponseError,
    AgentProviderRequestError,
    LocalStructuredProvider,
    MissingProviderConfigurationError,
    OpenAICompatibleProvider,
    ProviderConversation,
)
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput
from cloudhelm_agent_runtime.schemas.development_plan import DevelopmentPlanStep, PlannerAgentInput
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion, RequirementAgentInput, RequirementAgentOutput


def _without_cache_breakpoint(value):
    """移除显式缓存断点元数据，便于只比较模型 token 前缀。"""

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


class FakeHttpResponse:
    """测试用 urllib 响应上下文。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        """返回 UTF-8 JSON body。"""

        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __iter__(self):
        """把旧测试 payload 转成 Responses 或 Chat Completions SSE。"""

        if "choices" in self.payload:
            content = self.payload["choices"][0]["message"]["content"]
            events = [
                {"choices": [{"delta": {"content": content}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
            for event_payload in events:
                yield f"data: {json.dumps(event_payload, ensure_ascii=False)}\n".encode("utf-8")
                yield b"\n"
            yield b"data: [DONE]\n"
            yield b"\n"
            return

        text = self.payload.get("output_text")
        if not isinstance(text, str):
            for item in self.payload.get("output", []):
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        text = content.get("text")
                        break
        if isinstance(text, str):
            done_event = {
                "type": "response.output_text.done",
                "item_id": "msg_test",
                "output_index": 0,
                "content_index": 0,
                "text": text,
                "sequence_number": 1,
            }
            yield f"event: response.output_text.done\n".encode("utf-8")
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n".encode("utf-8")
            yield b"\n"
        completed_event = {
            "type": "response.completed",
            "response": self.payload,
            "sequence_number": 2,
        }
        yield b"event: response.completed\n"
        yield f"data: {json.dumps(completed_event, ensure_ascii=False)}\n".encode("utf-8")
        yield b"\n"

    def close(self) -> None:
        """兼容 `HTTPError` 对底层响应执行资源清理。"""

        return None


class FakeRawSseResponse:
    """直接发送指定 JSON 事件的 SSE 测试响应。"""

    def __init__(self, events: list[dict]) -> None:
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def __iter__(self):
        for event_payload in self.events:
            yield f"data: {json.dumps(event_payload, ensure_ascii=False)}\n".encode("utf-8")
            yield b"\n"


def test_requirement_agent_generates_valid_structured_output() -> None:
    """Requirement Agent 应从真实输入生成可校验需求规格。"""

    provider = LocalStructuredProvider()
    output = RequirementAgent(provider).run(
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="实现 Agent 编排",
            description="用户需要在控制台启动 M4 编排。必须展示事件和验收标准。",
            source_type="manual",
            source_ref=None,
            risk_level=RiskLevel.L1,
        )
    )

    assert output.user_story.startswith("作为 CloudHelm 使用者")
    assert output.acceptance_criteria[0].id == "AC-001"
    assert output.constraints[0].type == "source"


def test_architect_agent_marks_database_related_design_as_l2() -> None:
    """涉及数据库/迁移风险的设计应建议审批。"""

    provider = LocalStructuredProvider()
    requirement_output = RequirementAgent(provider).run(
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="新增开发计划表",
            description="需要新增数据库表并写入迁移，控制台可查询。",
            source_type="manual",
            risk_level=RiskLevel.L1,
        )
    )
    output = ArchitectAgent(provider).run(
        ArchitectAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            requirement_spec_id=uuid4(),
            title="新增开发计划表",
            user_story=requirement_output.user_story,
            acceptance_criteria=requirement_output.acceptance_criteria,
            constraints=requirement_output.constraints,
            task_risk_level=RiskLevel.L1,
        )
    )

    assert output.risk_level == RiskLevel.L2
    assert output.approval_recommended is True
    assert "development_plans" in str(output.db_schema_json)


def test_planner_agent_rejects_missing_step_dependency() -> None:
    """DevelopmentPlan schema 必须拒绝断裂依赖。"""

    with pytest.raises(ValidationError):
        from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentOutput

        PlannerAgentOutput(
            summary="坏计划",
            steps=[
                DevelopmentPlanStep(
                    id="STEP-001",
                    title="坏依赖",
                    description="依赖不存在的步骤。",
                    agent="tester",
                    expected_artifact="test",
                    depends_on=["STEP-999"],
                )
            ],
            risks=[],
            risk_level=RiskLevel.L1,
        )


def test_planner_agent_generates_task_graph() -> None:
    """Planner Agent 应输出可追溯任务图。"""

    output = PlannerAgent(LocalStructuredProvider()).run(
        PlannerAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            technical_design_id=uuid4(),
            title="实现 M4",
            design_summary="需要 Platform API、控制台和测试。",
            risk_level=RiskLevel.L1,
        )
    )

    assert [step.id for step in output.steps] == ["STEP-001", "STEP-002", "STEP-003", "STEP-004"]
    assert output.status == "ready_for_review"


def test_openai_compatible_provider_reports_missing_config() -> None:
    """缺少外部模型配置时不能静默写固定输出。"""

    provider = OpenAICompatibleProvider(api_base=None, api_key=None, model_name=None)
    with pytest.raises(MissingProviderConfigurationError):
        provider.generate(
            "requirement",
            RequirementAgentInput(
                task_id=uuid4(),
                project_id=uuid4(),
                title="配置缺失",
                description="验证缺配置错误。",
                source_type="manual",
                risk_level=RiskLevel.L1,
            ),
            AcceptanceCriterion,
        )


def test_openai_provider_keeps_explicit_max_reasoning_compatibility(monkeypatch) -> None:
    """默认 xhigh 之外，调用方显式配置 max 时也应原样透传。"""

    captured: dict = {}
    output = {
        "summary": "已整理需求。",
        "raw_input": "验证显式 max reasoning 兼容值。",
        "user_story": "作为调用方，我希望显式 max 配置被原样透传。",
        "constraints": [{"type": "api", "value": "使用 Responses API", "required": True}],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "显式 max 配置被原样透传", "verification": "pytest", "status": "pending"}
        ],
        "risk_level": "L1",
    }

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        captured["url"] = http_request.full_url
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        captured["timeout"] = timeout
        captured["user_agent"] = http_request.get_header("User-agent")
        captured["originator"] = http_request.get_header("Originator")
        return FakeHttpResponse(
            {
                "id": "resp_cache_test",
                "status": "completed",
                "usage": {
                    "input_tokens": 2048,
                    "input_tokens_details": {"cached_tokens": 1024},
                    "output_tokens": 256,
                },
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(output, ensure_ascii=False)}],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-5.6-sol",
        api_mode="responses",
        reasoning_effort="max",
        max_output_tokens=32768,
        user_agent="codex_cli_rs/0.0.0 (pytest)",
        originator="codex_cli_rs",
        explicit_cache_breakpoint=True,
    )
    result = provider.generate(
        "requirement",
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="兼容 GPT-5.6 Sol",
            description="验证显式 max reasoning 兼容值。",
            source_type="manual",
            risk_level=RiskLevel.L1,
        ),
        RequirementAgentOutput,
    )

    assert result["summary"] == "已整理需求。"
    assert captured["url"] == "https://api.example.test/v1/responses"
    assert captured["body"]["model"] == "gpt-5.6-sol"
    assert captured["body"]["reasoning"] == {
        "effort": "max",
        "summary": "auto",
        "context": "all_turns",
    }
    assert captured["body"]["max_output_tokens"] == 32768
    assert captured["body"]["store"] is False
    assert captured["body"]["stream"] is True
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert (
        captured["body"]["text"]["format"]["name"]
        == "cloudhelm_agent_output_v1"
    )
    assert captured["body"]["text"]["format"]["strict"] is False
    transport_schema = captured["body"]["text"]["format"]["schema"]
    assert transport_schema["required"] == ["summary", "risk_level"]
    assert transport_schema["additionalProperties"] is False
    assert "anyOf" not in transport_schema
    assert captured["body"]["prompt_cache_options"] == {"mode": "explicit"}
    assert captured["body"]["input"][-1]["content"][0][
        "prompt_cache_breakpoint"
    ] == {"mode": "explicit"}
    assert captured["user_agent"] == "codex_cli_rs/0.0.0 (pytest)"
    assert captured["originator"] == "codex_cli_rs"
    assert captured["body"]["prompt_cache_key"]
    assert captured["body"]["include"] == ["reasoning.encrypted_content"]
    assert provider.last_call_metadata is not None
    assert provider.last_call_metadata.response_id == "resp_cache_test"
    assert provider.last_call_metadata.input_tokens == 2048
    assert provider.last_call_metadata.cached_input_tokens == 1024
    assert provider.last_call_metadata.output_tokens == 256
    assert len(provider.last_call_metadata.request_usages) == 1
    assert provider.last_call_metadata.request_usages[0].to_json() == {
        "response_id": "resp_cache_test",
        "prompt_cache_key": captured["body"]["prompt_cache_key"],
        "input_tokens": 2048,
        "cached_input_tokens": 1024,
        "output_tokens": 256,
        "cache_hit": True,
    }


def test_openai_provider_keeps_chat_completions_fallback(monkeypatch) -> None:
    """旧 OpenAI-compatible 服务仍可切换到 Chat Completions。"""

    captured: dict = {}
    output = {
        "summary": "chat fallback",
        "raw_input": "fallback",
        "user_story": "作为用户，我希望兼容旧接口。",
        "constraints": [{"type": "api", "value": "chat_completions", "required": True}],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "返回结构化 JSON", "verification": "pytest", "status": "pending"}
        ],
        "risk_level": "L1",
    }

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        captured["url"] = http_request.full_url
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        return FakeHttpResponse({"choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}]})

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    result = OpenAICompatibleProvider(
        api_base="https://compat.example.test/v1",
        api_key="test-key",
        model_name="compat-model",
        api_mode="chat_completions",
        reasoning_effort="high",
    ).generate(
        "requirement",
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="兼容旧接口",
            description="fallback",
            source_type="manual",
            risk_level=RiskLevel.L1,
        ),
        RequirementAgentOutput,
    )

    assert result["summary"] == "chat fallback"
    assert captured["url"] == "https://compat.example.test/v1/chat/completions"
    assert captured["body"]["reasoning_effort"] == "high"
    assert captured["body"]["stream"] is True


def test_openai_provider_merges_and_appends_full_conversation_history(monkeypatch) -> None:
    """第二轮必须发送 user/assistant/user 完整历史，而不是只复用 cache key。"""

    captured_inputs: list[object] = []
    outputs = [
        {
            "summary": "第一轮。",
            "raw_input": "turn-1",
            "user_story": "作为用户，我希望保留第一轮。",
            "constraints": [{"type": "history", "value": "turn-1", "required": True}],
            "acceptance_criteria": [
                {"id": "AC-001", "description": "记录第一轮", "verification": "pytest", "status": "pending"}
            ],
            "risk_level": "L1",
        },
        {
            "summary": "第二轮。",
            "raw_input": "turn-2",
            "user_story": "作为用户，我希望第二轮包含历史。",
            "constraints": [{"type": "history", "value": "turn-1+turn-2", "required": True}],
            "acceptance_criteria": [
                {"id": "AC-001", "description": "合并历史", "verification": "pytest", "status": "pending"}
            ],
            "risk_level": "L1",
        },
    ]

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        request_body = json.loads(http_request.data.decode("utf-8"))
        captured_inputs.append(request_body["input"])
        output = outputs[len(captured_inputs) - 1]
        return FakeHttpResponse(
            {
                "id": f"resp_turn_{len(captured_inputs)}",
                "status": "completed",
                "usage": {
                    "input_tokens": 1024 * len(captured_inputs),
                    "input_tokens_details": {"cached_tokens": 0 if len(captured_inputs) == 1 else 1024},
                    "output_tokens": 128,
                },
                "output": [
                    {
                        "type": "reasoning",
                        "id": f"reasoning_{len(captured_inputs)}",
                        "summary": [],
                        "encrypted_content": f"encrypted-turn-{len(captured_inputs)}",
                    },
                    {
                        "type": "message",
                        "id": f"message_{len(captured_inputs)}",
                        "role": "assistant",
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

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-5.6-sol",
        reasoning_effort="xhigh",
    )
    conversation = ProviderConversation(conversation_id="conversation-test")
    agent = RequirementAgent(provider)
    for turn in (1, 2):
        agent.run(
            RequirementAgentInput(
                task_id=uuid4(),
                project_id=uuid4(),
                title=f"第 {turn} 轮",
                description=f"turn-{turn}",
                source_type="manual",
                risk_level=RiskLevel.L1,
            ),
            conversation=conversation,
        )

    assert isinstance(captured_inputs[0], list)
    assert isinstance(captured_inputs[1], list)
    assert _without_cache_breakpoint(
        captured_inputs[1][: len(captured_inputs[0])]
    ) == _without_cache_breakpoint(captured_inputs[0])
    assert [item["type"] for item in captured_inputs[1]] == [
        "message",
        "message",
        "reasoning",
        "message",
        "message",
        "message",
    ]
    assert captured_inputs[1][0]["role"] == "developer"
    assert captured_inputs[1][1]["role"] == "user"
    assert captured_inputs[1][2]["encrypted_content"] == "encrypted-turn-1"
    assert "id" not in captured_inputs[1][2]
    assert "id" not in captured_inputs[1][3]
    assert captured_inputs[1][3]["phase"] == "final_answer"
    assert outputs[0]["summary"] in json.dumps(captured_inputs[1][3], ensure_ascii=False)
    assert conversation.turn_count == 2


def test_openai_provider_rejects_missing_responses_output_text(monkeypatch) -> None:
    """Responses API 缺少 output_text 时返回稳定 provider 错误。"""

    monkeypatch.setattr(
        "cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen",
        lambda http_request, timeout: FakeHttpResponse({"status": "completed", "output": []}),
    )
    provider = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-5.6-sol",
    )

    with pytest.raises(AgentProviderResponseError):
        provider.generate(
            "requirement",
            RequirementAgentInput(
                task_id=uuid4(),
                project_id=uuid4(),
                title="坏响应",
                description="缺少 output_text",
                source_type="manual",
                risk_level=RiskLevel.L1,
            ),
            RequirementAgentOutput,
        )


def test_openai_provider_retries_transient_request_errors(monkeypatch) -> None:
    """瞬时网络错误应在固定次数内重试，而不是立即中止 AgentRun。"""

    attempts = 0
    output = {
        "summary": "重试后成功。",
        "raw_input": "retry",
        "user_story": "作为用户，我希望瞬时网络错误可恢复。",
        "constraints": [{"type": "network", "value": "bounded retry", "required": True}],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "第三次请求成功", "verification": "pytest", "status": "pending"}
        ],
        "risk_level": "L1",
    }

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise error.URLError("temporary")
        return FakeHttpResponse({"status": "completed", "output_text": json.dumps(output, ensure_ascii=False)})

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    result = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-5.6-sol",
        max_attempts=3,
        retry_backoff_seconds=0,
    ).generate(
        "requirement",
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="重试请求",
            description="retry",
            source_type="manual",
            risk_level=RiskLevel.L1,
        ),
        RequirementAgentOutput,
    )

    assert result["summary"] == "重试后成功。"
    assert attempts == 3


def test_openai_provider_retries_invalid_structured_output(monkeypatch) -> None:
    """首次无效 JSON 应重新生成，并由 Pydantic 校验第二次结果。"""

    attempts = 0
    instructions: list[str] = []
    request_inputs: list[list[dict]] = []
    valid_output = {
        "summary": "结构已修复。",
        "raw_input": "repair",
        "user_story": "作为用户，我希望无效结构可自动重试。",
        "constraints": [{"type": "schema", "value": "valid", "required": True}],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "输出可校验", "verification": "pytest", "status": "pending"}
        ],
        "risk_level": "L1",
    }

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        request_body = json.loads(http_request.data.decode("utf-8"))
        instructions.append(request_body["instructions"])
        request_inputs.append(request_body["input"])
        text = "{not-json" if attempts == 1 else json.dumps(valid_output, ensure_ascii=False)
        return FakeHttpResponse({"status": "completed", "output_text": text})

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    result = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-5.6-sol",
        max_attempts=2,
        retry_backoff_seconds=0,
    ).generate(
        "requirement",
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="修复结构",
            description="repair",
            source_type="manual",
            risk_level=RiskLevel.L1,
        ),
        RequirementAgentOutput,
    )

    assert result["summary"] == "结构已修复。"
    assert attempts == 2
    assert instructions[0] == instructions[1]
    assert "<validation_repair>" not in json.dumps(request_inputs[0], ensure_ascii=False)
    assert "<validation_repair>" in json.dumps(request_inputs[1], ensure_ascii=False)
    assert request_inputs[1][: len(request_inputs[0])] == request_inputs[0]


def test_openai_provider_retries_retryable_stream_error_with_server_delay(monkeypatch) -> None:
    """流内 server_error 应按 retry_after 等待并重新建立完整请求。"""

    attempts = 0
    sleeps: list[float] = []
    valid_output = {
        "summary": "流错误重试成功。",
        "raw_input": "stream retry",
        "user_story": "作为用户，我希望流内瞬时错误可恢复。",
        "constraints": [{"type": "stream", "value": "retry", "required": True}],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "第二次流成功", "verification": "pytest", "status": "pending"}
        ],
        "risk_level": "L1",
    }

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return FakeRawSseResponse(
                [
                    {
                        "type": "error",
                        "error": {
                            "code": "server_error",
                            "message": "temporary overload",
                            "retryable": True,
                            "retry_after": 7,
                        },
                    }
                ]
            )
        return FakeHttpResponse(
            {
                "id": "resp_retry_success",
                "status": "completed",
                "output_text": json.dumps(valid_output, ensure_ascii=False),
            }
        )

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.time.sleep", sleeps.append)
    result = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-5.6-sol",
        max_attempts=2,
        retry_backoff_seconds=1,
    ).generate(
        "requirement",
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="流错误重试",
            description="stream retry",
            source_type="manual",
            risk_level=RiskLevel.L1,
        ),
        RequirementAgentOutput,
    )

    assert result["summary"] == "流错误重试成功。"
    assert attempts == 2
    assert sleeps == [7]


def test_openai_provider_does_not_retry_non_retryable_http_error(monkeypatch) -> None:
    """认证类 4xx 请求错误不得通过重试放大无效流量。"""

    attempts = 0

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        raise error.HTTPError(
            http_request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=FakeHttpResponse({"error": {"message": "invalid key"}}),
        )

    monkeypatch.setattr("cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="bad-key",
        model_name="gpt-5.6-sol",
        max_attempts=3,
        retry_backoff_seconds=0,
    )

    with pytest.raises(AgentProviderRequestError) as captured:
        provider.generate(
            "requirement",
            RequirementAgentInput(
                task_id=uuid4(),
                project_id=uuid4(),
                title="认证失败",
                description="401",
                source_type="manual",
                risk_level=RiskLevel.L1,
            ),
            RequirementAgentOutput,
        )

    assert captured.value.retryable is False
    assert attempts == 1
