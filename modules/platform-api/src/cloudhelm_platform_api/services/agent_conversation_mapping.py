"""AgentConversation ORM 与 Agent Runtime conversation 的无副作用映射。"""

from copy import deepcopy

from cloudhelm_agent_runtime.providers import ProviderConversation

from cloudhelm_platform_api.models.agent_conversation import AgentConversation


def to_provider_conversation(
    record: AgentConversation,
) -> ProviderConversation:
    """复制数据库记录，构造可由 Provider 原子追加的会话对象。"""

    return ProviderConversation(
        conversation_id=str(record.id),
        items=deepcopy(record.items_json),
        turn_count=record.turn_count,
        last_response_id=record.last_response_id,
        prompt_cache_key=record.prompt_cache_key,
        source_type=record.source_type,
        parent_conversation_id=(
            str(record.parent_conversation_id)
            if record.parent_conversation_id
            else None
        ),
        agent_role=record.agent_role,
        depth=record.depth,
    )
