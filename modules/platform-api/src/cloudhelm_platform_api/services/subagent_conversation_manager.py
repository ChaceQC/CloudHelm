"""显式 subagent conversation 的创建、约束与完成回传。"""

from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.instructions import (
    subagent_instructions,
    subagent_task_item,
)
from cloudhelm_agent_runtime.providers import ProviderConversation
from cloudhelm_agent_runtime.providers.contracts import fork_items_for_subagent
from cloudhelm_agent_runtime.providers.subagent_notifications import (
    subagent_notification_item,
)
from cloudhelm_agent_runtime.providers.prompt_cache import build_prompt_cache_key

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.repositories.agent_conversation_repository import (
    AgentConversationRepository,
)
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.services.agent_conversation_mapping import (
    to_provider_conversation,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.subagent_conversation_audit import (
    record_subagent_spawned,
)
from cloudhelm_platform_api.services.subagent_conversation_policy import (
    SubagentConversationPolicy,
)

TERMINAL_SUBAGENT_STATUSES = {"completed", "failed", "cancelled"}


class SubagentConversationManager:
    """实现 subagent 生命周期；外部只能经 AgentConversationService 调用。"""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.conversations = AgentConversationRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.events = EventService(session)
        self.policy = SubagentConversationPolicy(session, settings)

    def spawn(
        self,
        *,
        parent_conversation_id: UUID,
        agent_role: str,
        nickname: str | None,
        objective: str,
        expected_result: str,
        spawned_by_agent_run_id: UUID,
        fork_context: bool,
    ) -> tuple[AgentConversation, ProviderConversation]:
        """校验父线程和执行配额后创建一个独立 child conversation。"""

        role, child_objective, expected = self.policy.normalize_request(
            agent_role,
            objective,
            expected_result,
        )
        parent_hint = self.conversations.get(parent_conversation_id)
        if parent_hint is None:
            raise ServiceError(
                "parent_agent_conversation_not_found",
                "创建子 Agent 失败：父会话不存在。",
                404,
            )
        self.policy.require_running_task(parent_hint.task_id)
        parent = self._require_active_parent(parent_conversation_id)
        depth = self.policy.validate_capacity(parent)
        spawning_run = self.policy.validate_spawning_run(
            parent,
            spawned_by_agent_run_id,
        )

        child_id = uuid4()
        tool_scope = self.policy.build_child_tool_scope(
            child_id,
            spawning_run,
            role,
        )
        items = fork_items_for_subagent(
            parent.items_json,
            fork_context=fork_context,
        )
        items.extend(
            [
                subagent_instructions(
                    parent_conversation_id=str(parent.id),
                    agent_role=role,
                    depth=depth,
                    fork_context=fork_context,
                    parent_agent_type=spawning_run.agent_type,
                    effective_allowed_tools=tool_scope.effective_allowed_tools,
                ),
                subagent_task_item(
                    objective=child_objective,
                    expected_result=expected,
                ),
            ]
        )
        child = self.conversations.create(
            AgentConversation(
                id=child_id,
                task_id=parent.task_id,
                parent_conversation_id=parent.id,
                spawned_by_agent_run_id=spawned_by_agent_run_id,
                source_type="subagent",
                agent_role=role,
                nickname=nickname,
                objective=child_objective,
                depth=depth,
                status="active",
                fork_mode="full_history" if fork_context else "fresh",
                provider_name=parent.provider_name,
                model_name=parent.model_name,
                prompt_cache_key=build_prompt_cache_key(
                    parent.model_name,
                    role,
                    None,
                    str(child_id),
                ),
                items_json=items,
                turn_count=0,
            )
        )
        record_subagent_spawned(
            self.events,
            child,
            parent,
            spawned_by_agent_run_id,
            child_objective,
        )
        return child, to_provider_conversation(child)

    def complete(
        self,
        conversation_id: UUID,
        *,
        status: str,
        summary: str,
    ) -> None:
        """关闭 child，并仅向父线程追加结构化最终通知。"""

        safe_summary = self.policy.normalize_summary(summary)
        child_hint = self.conversations.get(conversation_id)
        if child_hint is None:
            raise ServiceError(
                "agent_conversation_not_found",
                "子 Agent 会话不存在。",
                404,
            )
        self.policy.require_running_task(child_hint.task_id)
        child = self.conversations.get(conversation_id, for_update=True)
        assert child is not None
        if child.source_type != "subagent" or child.parent_conversation_id is None:
            raise ServiceError(
                "root_conversation_cannot_complete_as_subagent",
                "root conversation 不能按子 Agent 结束。",
                409,
            )
        self.policy.ensure_active(child)
        if status not in TERMINAL_SUBAGENT_STATUSES:
            raise ServiceError(
                "invalid_subagent_terminal_status",
                "子 Agent 终态必须为 completed、failed 或 cancelled。",
                422,
            )
        if self.agent_runs.list_active_by_conversation(child.id):
            raise ServiceError(
                "subagent_agent_run_active",
                "子 Agent 仍有 active AgentRun，不能先结束 conversation。",
                409,
            )
        if self.conversations.list_active_descendants(
            child.task_id,
            child.id,
            for_update=True,
        ):
            raise ServiceError(
                "subagent_descendants_active",
                "子 Agent 仍有 active 后代 conversation，不能先结束父 child。",
                409,
            )
        parent = self._require_active_parent(child.parent_conversation_id)

        child.status = status
        child.completed_at = utc_now()
        child.revision += 1
        parent_conversation = to_provider_conversation(parent)
        parent_conversation.append_context_item(
            subagent_notification_item(
                conversation_id=str(child.id),
                agent_role=child.agent_role or "subagent",
                status=status,
                summary=safe_summary,
            )
        )
        parent.items_json = deepcopy(parent_conversation.items)
        parent.revision += 1
        self.events.record(
            "SubagentCompleted" if status == "completed" else "SubagentStopped",
            "agent",
            str(child.id),
            {
                "conversation_id": str(child.id),
                "parent_conversation_id": str(parent.id),
                "agent_role": child.agent_role,
                "status": status,
                "summary": safe_summary,
            },
            child.task_id,
        )

    def _require_active_parent(
        self,
        conversation_id: UUID,
    ) -> AgentConversation:
        """读取并锁定 active 父会话。"""

        parent = self.conversations.get(conversation_id, for_update=True)
        if parent is None:
            raise ServiceError(
                "parent_agent_conversation_not_found",
                "创建或完成子 Agent 失败：父会话不存在。",
                404,
            )
        self.policy.ensure_active(parent)
        return parent
