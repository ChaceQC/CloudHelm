"""真实 Responses API Prompt Cache 集成测试。

该文件默认跳过；只有显式启用并注入真实凭据时，才发送五轮具有长公共
前缀的 `gpt-5.6-sol` 请求，并要求第 2-5 轮 usage 持续出现 cached tokens。
"""

import os
from uuid import uuid4

import pytest

from cloudhelm_agent_runtime.agents import RequirementAgent
from cloudhelm_agent_runtime.providers import OpenAICompatibleProvider, ProviderConversation
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.requirement import RequirementAgentInput

pytestmark = pytest.mark.skipif(
    os.environ.get("CLOUDHELM_RUN_EXTERNAL_LLM_TESTS") != "1",
    reason="需要显式启用真实外部模型测试。",
)


def test_real_five_turn_prompt_cache_hits_after_first_turn() -> None:
    """同一 Task 的五轮长公共前缀请求必须在后四轮命中缓存。"""

    api_base = os.environ.get("CLOUDHELM_LLM_API_BASE")
    api_key = os.environ.get("CLOUDHELM_LLM_API_KEY")
    if not api_base or not api_key:
        pytest.skip("未注入真实 CLOUDHELM_LLM_API_BASE/CLOUDHELM_LLM_API_KEY。")
    assert os.environ.get("CLOUDHELM_LLM_MODEL", "gpt-5.6-sol") == "gpt-5.6-sol"
    assert os.environ.get("CLOUDHELM_LLM_REASONING_EFFORT", "xhigh") == "xhigh"

    provider = OpenAICompatibleProvider(
        api_base=api_base,
        api_key=api_key,
        model_name="gpt-5.6-sol",
        api_mode="responses",
        reasoning_effort="xhigh",
        max_output_tokens=16384,
        timeout_seconds=300,
        max_attempts=5,
        retry_backoff_seconds=5,
        user_agent="codex_cli_rs/0.0.0 (CloudHelm cache pytest)",
        originator="codex_cli_rs",
    )
    task_id = uuid4()
    project_id = uuid4()
    conversation = ProviderConversation(conversation_id=str(task_id))
    stable_prefix = (
        "CloudHelm 需要任务时间线、分页 API、审批审计、数据库迁移、"
        "黑盒测试、白盒测试和响应式控制台验证。"
    ) * 35
    cache_keys: list[str | None] = []
    input_tokens: list[int] = []
    cached_tokens: list[int] = []
    response_ids: list[str | None] = []

    for turn in range(1, 6):
        RequirementAgent(provider).run(
            RequirementAgentInput(
                task_id=task_id,
                project_id=project_id,
                title="多轮 Prompt Cache 真实验证",
                description=f"{stable_prefix}\n当前轮次：{turn}。保持输出精炼。",
                source_type="manual",
                risk_level=RiskLevel.L2,
            ),
            conversation=conversation,
        )
        metadata = provider.last_call_metadata
        assert metadata is not None
        assert metadata.input_tokens >= 1024
        assert metadata.conversation_id == str(task_id)
        assert metadata.conversation_turn == turn
        assert metadata.request_count == 1
        assert len(metadata.request_usages) == 1
        request_usage = metadata.request_usages[0]
        assert request_usage.input_tokens == metadata.input_tokens
        assert request_usage.cached_input_tokens == metadata.cached_input_tokens
        assert request_usage.output_tokens == metadata.output_tokens
        cache_keys.append(metadata.prompt_cache_key)
        input_tokens.append(metadata.input_tokens)
        cached_tokens.append(metadata.cached_input_tokens)
        response_ids.append(metadata.response_id)
        print(
            f"turn={turn} input_tokens={metadata.input_tokens} "
            f"cached_input_tokens={metadata.cached_input_tokens} "
            f"conversation_turn={metadata.conversation_turn} "
            f"response_id_present={metadata.response_id is not None} "
            f"provider_request_count={metadata.request_count} "
            f"cache_hit={request_usage.cached_input_tokens > 0}"
        )

    assert len(set(cache_keys)) == 1
    assert all(response_ids)
    assert cached_tokens[0] == 0
    assert all(
        left < right
        for left, right in zip(input_tokens[:-1], input_tokens[1:], strict=True)
    ), input_tokens
    assert all(value > 0 for value in cached_tokens[1:]), cached_tokens
    assert all(
        left < right
        for left, right in zip(cached_tokens[1:-1], cached_tokens[2:], strict=True)
    ), cached_tokens
    assert conversation.turn_count == 5
