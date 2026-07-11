"""供应商调用的逐请求 usage 与 AgentRun 聚合元数据。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cloudhelm_agent_runtime.providers.contracts import ProviderConversation


@dataclass(frozen=True, slots=True)
class ProviderRequestUsage:
    """一次已完成供应商请求返回的原始 usage 证据。"""

    response_id: str | None = None
    prompt_cache_key: str | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        """转换为可写入 JSONB/API/EventLog 的稳定结构。"""

        return {
            "response_id": self.response_id,
            "prompt_cache_key": self.prompt_cache_key,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "cache_hit": self.cached_input_tokens > 0,
        }


@dataclass(frozen=True, slots=True)
class ProviderCallMetadata:
    """一个 AgentRun 的供应商用量总计与逐请求证据。"""

    response_id: str | None = None
    prompt_cache_key: str | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 1
    conversation_id: str | None = None
    conversation_turn: int | None = None
    request_usages: tuple[ProviderRequestUsage, ...] = ()

    def with_conversation(
        self,
        conversation: ProviderConversation,
    ) -> ProviderCallMetadata:
        """补充调用完成后的会话标识和 turn，保持对象不可变。"""

        return replace(
            self,
            conversation_id=conversation.conversation_id,
            conversation_turn=conversation.turn_count,
        )
