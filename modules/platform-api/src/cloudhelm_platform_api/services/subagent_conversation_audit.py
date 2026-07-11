"""Subagent conversation 生命周期的脱敏审计事件。"""

import hashlib
from uuid import UUID

from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.services.event_service import EventService


def record_subagent_spawned(
    events: EventService,
    child: AgentConversation,
    parent: AgentConversation,
    spawned_by_agent_run_id: UUID,
    objective: str,
) -> None:
    """记录 spawn 元数据和目标 hash，不把原始子目标写入 EventLog。"""

    events.record(
        "SubagentSpawned",
        "agent",
        str(spawned_by_agent_run_id),
        {
            "conversation_id": str(child.id),
            "parent_conversation_id": str(parent.id),
            "agent_role": child.agent_role,
            "nickname": child.nickname,
            "objective_sha256": hashlib.sha256(
                objective.encode("utf-8")
            ).hexdigest(),
            "depth": child.depth,
            "fork_mode": child.fork_mode,
        },
        parent.task_id,
    )
