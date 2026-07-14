"""Codex 风格 Task root / subagent conversation 管理。"""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.providers import (
    ProviderCallMetadata,
    ProviderConversation,
)
from cloudhelm_agent_runtime.providers.prompt_cache import build_prompt_cache_key

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.agent_conversation_repository import (
    AgentConversationRepository,
)
from cloudhelm_platform_api.services.agent_conversation_mapping import (
    to_provider_conversation,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.subagent_conversation_manager import (
    SubagentConversationManager,
)


class AgentConversationService:
    """维护一个 Task 的 root thread 和显式 subagent child threads。"""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.conversations = AgentConversationRepository(session)
        self.events = EventService(session)
        self.subagents = SubagentConversationManager(session, settings)

    def load_or_create_root(
        self,
        task: Task,
        *,
        provider_name: str,
        model_name: str | None,
    ) -> tuple[AgentConversation, ProviderConversation]:
        """锁定并返回 Task 唯一 root conversation。

        Requirement、Architect、Planner 等普通角色必须只调用本方法，不能按
        agent_type 创建新会话。
        """

        record = self.conversations.get_root(task.id, for_update=True)
        if record is None:
            conversation_id = uuid4()
            record = self.conversations.create(
                AgentConversation(
                    id=conversation_id,
                    task_id=task.id,
                    source_type="root",
                    parent_conversation_id=None,
                    spawned_by_agent_run_id=None,
                    agent_role=None,
                    nickname=None,
                    objective=None,
                    depth=0,
                    status="active",
                    fork_mode=None,
                    provider_name=provider_name,
                    model_name=model_name,
                    prompt_cache_key=build_prompt_cache_key(
                        model_name,
                        "root",
                        None,
                        str(conversation_id),
                    ),
                    items_json=[],
                    turn_count=0,
                )
            )
            self.events.record(
                "AgentConversationCreated",
                "orchestrator",
                "root",
                {
                    "conversation_id": str(record.id),
                    "source_type": "root",
                    "provider": provider_name,
                    "model": model_name,
                },
                task.id,
            )
        self._ensure_provider_compatible(record, provider_name, model_name)
        self._ensure_active(record)
        return record, to_provider_conversation(record)

    def save_turn(
        self,
        record: AgentConversation,
        conversation: ProviderConversation,
        metadata: ProviderCallMetadata | None,
        *,
        expected_revision: int | None = None,
    ) -> None:
        """在业务事务内保存已通过 schema 的完整 conversation turn。"""

        if str(record.id) != conversation.conversation_id:
            raise ServiceError(
                "agent_conversation_identity_mismatch",
                "Provider conversation 与数据库记录不一致。",
                409,
            )
        current = self.conversations.get(record.id, for_update=True)
        if current is None:
            raise ServiceError(
                "agent_conversation_not_found",
                "Agent conversation 不存在。",
                404,
            )
        if (
            expected_revision is not None
            and current.revision != expected_revision
        ):
            raise ServiceError(
                "agent_conversation_revision_conflict",
                "Agent 执行期间 conversation 已被其他请求更新，请重试当前步骤。",
                409,
                {
                    "expected_revision": expected_revision,
                    "actual_revision": current.revision,
                },
            )
        record = current
        self._ensure_active(record)
        if (
            metadata is not None
            and metadata.prompt_cache_key is not None
            and metadata.prompt_cache_key != record.prompt_cache_key
        ):
            raise ServiceError(
                "agent_conversation_cache_key_mismatch",
                "Provider 返回的 prompt_cache_key 与 Task conversation 不一致。",
                409,
            )
        record.items_json = deepcopy(conversation.items)
        record.turn_count = conversation.turn_count
        record.last_response_id = conversation.last_response_id
        record.revision += 1

    def append_root_context_if_exists(
        self,
        task_id: UUID,
        item: dict,
    ) -> None:
        """向现有 root conversation 追加审批等上下文；无模型会话时不凭空创建。"""

        record = self.conversations.get_root(task_id, for_update=True)
        if record is None:
            return
        self._ensure_active(record)
        conversation = to_provider_conversation(record)
        conversation.append_context_item(item)
        record.items_json = deepcopy(conversation.items)
        record.revision += 1

    def spawn_subagent(
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
        """显式创建 child conversation；这是唯一允许新会话的业务入口。"""

        return self.subagents.spawn(
            parent_conversation_id=parent_conversation_id,
            agent_role=agent_role,
            nickname=nickname,
            objective=objective,
            expected_result=expected_result,
            spawned_by_agent_run_id=spawned_by_agent_run_id,
            fork_context=fork_context,
        )

    def complete_subagent(
        self,
        conversation_id: UUID,
        *,
        status: str,
        summary: str,
    ) -> None:
        """关闭子会话并把最终摘要作为通知追加到父会话。"""

        self.subagents.complete(
            conversation_id,
            status=status,
            summary=summary,
        )

    @staticmethod
    def _ensure_provider_compatible(
        record: AgentConversation,
        provider_name: str,
        model_name: str | None,
    ) -> None:
        """禁止同一 conversation 中途切换 Provider 或模型。"""

        if (
            record.provider_name != provider_name
            or record.model_name != model_name
        ):
            raise ServiceError(
                "agent_conversation_provider_mismatch",
                "同一 Task conversation 不能中途切换 Provider 或模型。",
                409,
                {
                    "conversation_provider": record.provider_name,
                    "conversation_model": record.model_name,
                    "requested_provider": provider_name,
                    "requested_model": model_name,
                },
            )

    @staticmethod
    def _ensure_active(record: AgentConversation) -> None:
        """终态 conversation 不得继续追加模型或上下文。"""

        if record.status != "active":
            raise ServiceError(
                "agent_conversation_not_active",
                "当前 Agent conversation 已结束，不能继续写入。",
                409,
            )
