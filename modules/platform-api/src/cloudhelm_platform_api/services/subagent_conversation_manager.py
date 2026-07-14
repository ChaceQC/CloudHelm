"""显式 subagent conversation 的创建、约束与完成回传。"""

from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.instructions import (
    subagent_instructions,
    subagent_task_item,
)
from cloudhelm_agent_runtime.providers import ProviderConversation
from cloudhelm_agent_runtime.providers.contracts import (
    fork_items_for_subagent,
    subagent_notification_item,
)
from cloudhelm_agent_runtime.providers.prompt_cache import build_prompt_cache_key

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.repositories.agent_conversation_repository import (
    AgentConversationRepository,
)
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.schemas.common import AgentRunStatus
from cloudhelm_platform_api.services.agent_conversation_mapping import (
    to_provider_conversation,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.subagent_conversation_audit import (
    record_subagent_spawned,
)

MAX_SUBAGENT_OBJECTIVE_CHARS = 12000
TERMINAL_SUBAGENT_STATUSES = {"completed", "failed", "cancelled"}


class SubagentConversationManager:
    """实现 subagent 生命周期；外部只能经 AgentConversationService 调用。"""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.conversations = AgentConversationRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.events = EventService(session)

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

        role, child_objective, expected = self._normalize_request(
            agent_role,
            objective,
            expected_result,
        )
        parent = self._require_active_parent(parent_conversation_id)
        depth = self._validate_capacity(parent)
        self._validate_spawning_run(parent, spawned_by_agent_run_id)

        child_id = uuid4()
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

        child = self.conversations.get(conversation_id, for_update=True)
        if child is None:
            raise ServiceError(
                "agent_conversation_not_found",
                "子 Agent 会话不存在。",
                404,
            )
        if child.source_type != "subagent" or child.parent_conversation_id is None:
            raise ServiceError(
                "root_conversation_cannot_complete_as_subagent",
                "root conversation 不能按子 Agent 结束。",
                409,
            )
        self._ensure_active(child)
        if status not in TERMINAL_SUBAGENT_STATUSES:
            raise ServiceError(
                "invalid_subagent_terminal_status",
                "子 Agent 终态必须为 completed、failed 或 cancelled。",
                422,
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
                summary=summary,
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
                "summary": summary,
            },
            child.task_id,
        )

    @staticmethod
    def _normalize_request(
        agent_role: str,
        objective: str,
        expected_result: str,
    ) -> tuple[str, str, str]:
        """清理并校验 subagent 的角色、目标和预期交付。"""

        role = agent_role.strip()
        child_objective = objective.strip()
        expected = expected_result.strip()
        if not role:
            raise ServiceError(
                "invalid_subagent_role",
                "创建子 Agent 失败：agent_role 不能为空。",
                422,
            )
        if not child_objective:
            raise ServiceError(
                "invalid_subagent_objective",
                "创建子 Agent 失败：objective 不能为空。",
                422,
            )
        if len(child_objective) > MAX_SUBAGENT_OBJECTIVE_CHARS:
            raise ServiceError(
                "subagent_objective_too_long",
                "创建子 Agent 失败：objective 超过 12000 个字符。",
                422,
            )
        if not expected:
            raise ServiceError(
                "invalid_subagent_expected_result",
                "创建子 Agent 失败：expected_result 不能为空。",
                422,
            )
        return role, child_objective, expected

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
        self._ensure_active(parent)
        return parent

    def _validate_capacity(self, parent: AgentConversation) -> int:
        """校验 child 深度和单 Task active thread 上限。"""

        depth = parent.depth + 1
        if depth > self.settings.agent_max_subagent_depth:
            raise ServiceError(
                "subagent_depth_limit_exceeded",
                "创建子 Agent 失败：超过允许的会话深度。",
                409,
            )
        if (
            self.conversations.count_active_subagents(parent.task_id)
            >= self.settings.agent_max_subagent_threads
        ):
            raise ServiceError(
                "subagent_thread_limit_exceeded",
                "创建子 Agent 失败：当前任务 active 子会话已达上限。",
                409,
            )
        return depth

    def _validate_spawning_run(
        self,
        parent: AgentConversation,
        spawned_by_agent_run_id: UUID,
    ) -> None:
        """只允许同 Task 的 running AgentRun 显式 spawn。"""

        spawning_run = self.agent_runs.get(spawned_by_agent_run_id)
        if spawning_run is None:
            raise ServiceError(
                "spawning_agent_run_not_found",
                "创建子 Agent 失败：父 AgentRun 不存在。",
                404,
            )
        if spawning_run.task_id != parent.task_id:
            raise ServiceError(
                "spawning_agent_run_task_mismatch",
                "创建子 Agent 失败：父 AgentRun 不属于当前 Task。",
                409,
            )
        if spawning_run.status != AgentRunStatus.RUNNING.value:
            raise ServiceError(
                "spawning_agent_run_not_running",
                "只有 running AgentRun 可以显式创建子 Agent。",
                409,
            )

    @staticmethod
    def _ensure_active(record: AgentConversation) -> None:
        """终态 conversation 不得继续创建 child 或接收通知。"""

        if record.status != "active":
            raise ServiceError(
                "agent_conversation_not_active",
                "当前 Agent conversation 已结束，不能继续写入。",
                409,
            )
