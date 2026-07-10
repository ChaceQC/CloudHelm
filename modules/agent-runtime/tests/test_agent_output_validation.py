"""Agent Runtime 结构化输出白盒测试。"""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cloudhelm_agent_runtime.agents import ArchitectAgent, PlannerAgent, RequirementAgent
from cloudhelm_agent_runtime.providers import (
    AgentProviderResponseError,
    LocalStructuredProvider,
    MissingProviderConfigurationError,
    OpenAICompatibleProvider,
)
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput
from cloudhelm_agent_runtime.schemas.development_plan import DevelopmentPlanStep, PlannerAgentInput
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion, RequirementAgentInput, RequirementAgentOutput


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


def test_openai_provider_uses_responses_api_with_max_reasoning(monkeypatch) -> None:
    """gpt-5.6-sol 配置应通过 Responses API 发送 `reasoning.effort=max`。"""

    captured: dict = {}
    output = {
        "summary": "已整理需求。",
        "raw_input": "实现 max reasoning 兼容。",
        "user_story": "作为用户，我希望模型使用最大推理强度。",
        "constraints": [{"type": "api", "value": "使用 Responses API", "required": True}],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "请求包含 reasoning.effort=max", "verification": "pytest", "status": "pending"}
        ],
        "risk_level": "L1",
    }

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        captured["url"] = http_request.full_url
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeHttpResponse(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
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
    )
    result = provider.generate(
        "requirement",
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="兼容 GPT-5.6 Sol",
            description="实现 max reasoning 兼容。",
            source_type="manual",
            risk_level=RiskLevel.L1,
        ),
        RequirementAgentOutput,
    )

    assert result["summary"] == "已整理需求。"
    assert captured["url"] == "https://api.example.test/v1/responses"
    assert captured["body"]["model"] == "gpt-5.6-sol"
    assert captured["body"]["reasoning"] == {"effort": "max"}
    assert captured["body"]["max_output_tokens"] == 32768
    assert captured["body"]["store"] is False
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert captured["body"]["text"]["format"]["strict"] is False


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
