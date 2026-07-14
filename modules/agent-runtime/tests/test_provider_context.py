"""Provider Instructions、ResponseItem、工具与子会话白盒测试。"""

import json
from uuid import uuid4

import pytest

from cloudhelm_agent_runtime.agents import (
    ArchitectAgent,
    CoderAgent,
    PlannerAgent,
    RequirementAgent,
    ReviewerAgent,
    ScaffoldAgent,
    SecurityAgent,
    TesterAgent as RuntimeTesterAgent,
)
from cloudhelm_agent_runtime.instructions import (
    allowed_tools_for,
    base_instructions,
    build_turn_input_items,
    role_instructions,
    subagent_instructions,
)
from cloudhelm_agent_runtime.providers import (
    ProviderConversation,
    ProviderToolCall,
    ProviderToolDefinition,
    collect_tool_calls,
    tool_result_item,
)
from cloudhelm_agent_runtime.providers.contracts import (
    assistant_message_item,
    fork_items_for_subagent,
    function_call_output_item,
    normalize_response_item,
    validate_conversation_items,
)
from cloudhelm_agent_runtime.providers.output_schema import stable_output_schema
from cloudhelm_agent_runtime.providers.subagent_notifications import (
    MAX_SUBAGENT_SUMMARY_CHARS,
    subagent_notification_item,
)
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentOutput
from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentOutput
from cloudhelm_agent_runtime.schemas.implementation import CoderAgentOutput
from cloudhelm_agent_runtime.schemas.requirement import (
    RequirementAgentInput,
    RequirementAgentOutput,
)
from cloudhelm_agent_runtime.schemas.review_report import ReviewerAgentOutput
from cloudhelm_agent_runtime.schemas.scaffold import ScaffoldAgentOutput
from cloudhelm_agent_runtime.schemas.security_report import SecurityAgentOutput
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentOutput as TestReportOutput


def _requirement_input() -> RequirementAgentInput:
    """构造测试用 Requirement 输入。"""

    return RequirementAgentInput(
        task_id=uuid4(),
        project_id=uuid4(),
        title="验证分层 Instructions",
        description="要求上下文、工具和子 Agent 管理可审计。",
        source_type="manual",
        risk_level=RiskLevel.L2,
    )


def test_base_instructions_are_detailed_stable_and_role_neutral() -> None:
    """Base Instructions 必须完整且不绑定单一 Agent 角色。"""

    first = base_instructions()
    second = base_instructions()

    assert first == second
    assert len(first) >= 5000
    for heading in (
        "身份、任务与会话不变量",
        "指令优先级与可信边界",
        "每个 turn 的处理协议",
        "上下文、reasoning 与可见结论",
        "当前输出契约与稳定传输 schema",
        "工具调用协议",
        "审批、风险和副作用",
        "Subagent 边界",
        "真实性、失败与完成判定",
    ):
        assert heading in first
    assert "角色变化" in first
    assert "只有" in first and "subagent" in first
    assert "cloudhelm_agent_output_v1" in first
    assert "cached_input_tokens" in first
    assert "Requirement Agent Role Instructions" not in first


@pytest.mark.parametrize(
    ("agent_type", "agent_class", "required_phrases", "minimum_length"),
    [
        (
            "requirement",
            RequirementAgent,
            ("用户故事", "验收标准", "不得声称测试已经通过"),
            4000,
        ),
        (
            "architect",
            ArchitectAgent,
            ("OpenAPI 3.1", "数据库", "人工设计审批"),
            4000,
        ),
        (
            "planner",
            PlannerAgent,
            ("STEP-001", "depends_on", "ready_for_review"),
            4000,
        ),
        (
            "scaffold",
            ScaffoldAgent,
            ("planned_files", "repo.write_file", "ScaffoldAgentOutput"),
            1200,
        ),
        (
            "coder",
            CoderAgent,
            ("planned_changes", "repo.write_file", "CoderAgentOutput"),
            1200,
        ),
        (
            "tester",
            RuntimeTesterAgent,
            ("exit code", "failure_reasons", "TesterAgentOutput"),
            1200,
        ),
        (
            "reviewer",
            ReviewerAgent,
            ("Acceptance Criteria", "proceed_to_security", "ReviewerAgentOutput"),
            1200,
        ),
        (
            "security",
            SecurityAgent,
            ("FINDING-001", "blocking", "SecurityAgentOutput"),
            1200,
        ),
    ],
)
def test_role_instructions_are_precise_and_match_tool_policy(
    agent_type: str,
    agent_class,
    required_phrases: tuple[str, ...],
    minimum_length: int,
) -> None:
    """角色 Instructions 必须覆盖流程、输出、工具、禁止项和完成判定。"""

    instructions = role_instructions(agent_type)

    assert len(instructions) >= minimum_length
    for section in ("当前职责与唯一目标", "输入字段", "精度要求", "工具", "完成判定"):
        assert section in instructions
    for phrase in required_phrases:
        assert phrase in instructions
    assert tuple(agent_class.allowed_tools) == allowed_tools_for(agent_type)
    contract_text = instructions.split("<role_contract>", maxsplit=1)[1].split("</role_contract>", maxsplit=1)[0]
    contract = json.loads(contract_text)
    assert tuple(contract["allowed_tools"]) == allowed_tools_for(agent_type)
    assert contract["conversation_rule"] == "reuse_root_unless_explicit_subagent_spawn"
    assert contract["output_contract"].endswith("AgentOutput")
    assert contract["output_transport_schema"] == "cloudhelm_agent_output_v1"
    assert contract["side_effect_policy"] == "tool_gateway_and_approval_only"


def test_turn_items_keep_base_stable_and_put_validation_repair_in_context() -> None:
    """格式修复不得修改稳定 Base Instructions，只扩展当前 turn input。"""

    payload = _requirement_input()
    normal_items = build_turn_input_items("requirement", payload)
    repair_items = build_turn_input_items(
        "requirement",
        payload,
        validation_feedback="steps.0.id 不符合 STEP-[0-9]{3}",
    )
    cache_items = build_turn_input_items(
        "requirement",
        payload,
        explicit_cache_breakpoint=True,
    )

    assert normal_items == repair_items[: len(normal_items)]
    assert [item["role"] for item in normal_items] == ["developer", "user"]
    assert "prompt_cache_breakpoint" not in normal_items[-1]["content"][0]
    assert cache_items[-1]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    user_envelope = json.loads(normal_items[-1]["content"][0]["text"])
    assert user_envelope["conversation_scope"] == "task_root"
    assert user_envelope["output_contract"] == "RequirementAgentOutput"
    assert repair_items[-1]["role"] == "developer"
    assert "<validation_repair>" in repair_items[-1]["content"][0]["text"]
    assert "重新输出目标 contract 的完整 JSON object" in repair_items[-1]["content"][0]["text"]
    assert "RequirementAgentOutput" in repair_items[-1]["content"][0]["text"]


def test_stable_transport_schema_is_flat_and_covers_every_role_output() -> None:
    """跨角色 schema 必须相同、无根级联合，并覆盖所有 Pydantic 字段。"""

    models = (
        RequirementAgentOutput,
        ArchitectAgentOutput,
        PlannerAgentOutput,
        ScaffoldAgentOutput,
        CoderAgentOutput,
        TestReportOutput,
        ReviewerAgentOutput,
        SecurityAgentOutput,
    )
    schemas = [stable_output_schema(model) for model in models]

    assert schemas[0] == schemas[1] == schemas[2]
    schema = schemas[0]
    assert "anyOf" not in schema
    assert "$defs" not in schema
    assert schema["required"] == ["summary", "risk_level"]
    transport_fields = set(schema["properties"])
    for model in models:
        assert set(model.model_fields).issubset(transport_fields)


def test_response_items_preserve_reasoning_phase_and_tool_fields_without_ids() -> None:
    """可重放 item 只移除 id/内部 metadata，不丢 reasoning 或工具字段。"""

    reasoning = normalize_response_item(
        {
            "id": "rs_1",
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "检查引用闭合"}],
            "encrypted_content": "ciphertext",
            "status": "completed",
        }
    )
    message = normalize_response_item(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "phase": "final_answer",
            "content": [{"type": "output_text", "text": "{}"}],
        }
    )
    call = normalize_response_item(
        {
            "id": "fc_1",
            "type": "function_call",
            "name": "repo.read_file",
            "arguments": '{"path":"README.md"}',
            "call_id": "call_1",
            "status": "completed",
        }
    )

    assert "id" not in reasoning and reasoning["encrypted_content"] == "ciphertext"
    assert reasoning["status"] == "completed"
    assert message["phase"] == "final_answer"
    assert call["call_id"] == "call_1"
    assert call["status"] == "completed"


def test_tool_call_and_output_must_be_paired_and_are_replayable() -> None:
    """Tool Gateway 结果必须使用模型 call_id 成对回放。"""

    call_item = {
        "type": "function_call",
        "name": "repo.read_file",
        "arguments": '{"path":"README.md"}',
        "call_id": "call_1",
    }
    call = collect_tool_calls([call_item])[0]
    output_item = tool_result_item(
        call,
        status="succeeded",
        result={"path": "README.md", "content": "已脱敏结果"},
    )

    assert call == ProviderToolCall(
        call_id="call_1",
        name="repo.read_file",
        arguments={"path": "README.md"},
    )
    assert output_item["call_id"] == "call_1"
    validate_conversation_items([call_item, output_item])
    with pytest.raises(ValueError, match="no earlier matching call"):
        validate_conversation_items([function_call_output_item("orphan", "result")])


def test_tool_definition_uses_responses_function_shape() -> None:
    """工具声明必须映射为 Responses function tool JSON Schema。"""

    definition = ProviderToolDefinition(
        name="repo.read_file",
        description="读取受控工作区内 UTF-8 文件。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )

    assert definition.to_responses_json() == {
        "type": "function",
        "name": "repo.read_file",
        "description": "读取受控工作区内 UTF-8 文件。",
        "parameters": definition.parameters,
        "strict": False,
    }


def test_only_explicit_subagent_fork_creates_filtered_child_history() -> None:
    """子 Agent 只继承 Codex 允许的消息，不复制父 reasoning/tool 执行状态。"""

    parent_items = [
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": "父任务边界"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "父任务需求"}],
        },
        {
            "type": "reasoning",
            "summary": [],
            "encrypted_content": "parent-secret-reasoning",
        },
        {
            "type": "function_call",
            "name": "repo.read_file",
            "arguments": '{"path":"README.md"}',
            "call_id": "call_parent",
        },
        function_call_output_item("call_parent", "parent tool output"),
        assistant_message_item('{"summary":"父线程最终结果"}'),
    ]

    assert fork_items_for_subagent(parent_items, fork_context=False) == []
    forked = fork_items_for_subagent(parent_items, fork_context=True)
    assert [item["type"] for item in forked] == ["message", "message", "message"]
    serialized = json.dumps(forked, ensure_ascii=False)
    assert "父任务边界" in serialized
    assert "父线程最终结果" in serialized
    assert "parent-secret-reasoning" not in serialized
    assert "parent tool output" not in serialized


def test_subagent_instructions_include_parent_role_depth_and_fork_mode() -> None:
    """子会话指令必须携带可审计父子关系与权限边界。"""

    item = subagent_instructions(
        parent_conversation_id="parent-thread",
        agent_role="reviewer",
        depth=1,
        fork_context=True,
        parent_agent_type="planner",
        effective_allowed_tools=(
            "repo.list_files",
            "repo.read_file",
            "repo.search_text",
        ),
    )
    text = item["content"][0]["text"]

    assert item["role"] == "developer"
    assert "独立 child conversation" in text
    assert '"parent_conversation_id": "parent-thread"' in text
    assert '"agent_role": "reviewer"' in text
    assert '"parent_agent_type": "planner"' in text
    assert '"depth": 1' in text
    assert '"fork_context": true' in text
    assert (
        '"effective_allowed_tools": ["repo.list_files", "repo.read_file", '
        '"repo.search_text"]'
        in text
    )
    assert (
        '"permission_inheritance": "parent_or_stricter_via_tool_gateway"'
        in text
    )


def test_subagent_notification_requires_a_bounded_summary() -> None:
    """父线程只接收简洁最终摘要，不接收空值或整段原始日志。"""

    with pytest.raises(ValueError, match="non-empty"):
        subagent_notification_item(
            conversation_id="child-thread",
            agent_role="reviewer",
            status="completed",
            summary=" ",
        )
    with pytest.raises(ValueError, match="4000"):
        subagent_notification_item(
            conversation_id="child-thread",
            agent_role="reviewer",
            status="completed",
            summary="x" * (MAX_SUBAGENT_SUMMARY_CHARS + 1),
        )


def test_provider_conversation_appends_full_turn_and_tracks_response_id() -> None:
    """一个 root conversation 应原子保存 role/user/reasoning/final answer。"""

    conversation = ProviderConversation(
        conversation_id="root-thread",
        prompt_cache_key="cloudhelm:root-thread",
    )
    turn_items = build_turn_input_items(
        "requirement",
        _requirement_input(),
        explicit_cache_breakpoint=True,
    )
    conversation.append_turn(
        turn_items,
        [
            {
                "type": "reasoning",
                "summary": [],
                "encrypted_content": "encrypted",
            },
            assistant_message_item('{"summary":"done"}'),
        ],
        response_id="resp_1",
    )

    assert conversation.turn_count == 1
    assert conversation.last_response_id == "resp_1"
    assert [item["role"] for item in conversation.items if item["type"] == "message"] == [
        "developer",
        "user",
        "assistant",
    ]
    persisted_user = next(
        item
        for item in conversation.items
        if item.get("type") == "message" and item.get("role") == "user"
    )
    assert persisted_user["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
