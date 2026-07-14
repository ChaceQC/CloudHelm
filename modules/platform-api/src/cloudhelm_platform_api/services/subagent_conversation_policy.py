"""Codex CLI 式 subagent 创建、权限和摘要边界策略。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.providers.subagent_notifications import MAX_SUBAGENT_SUMMARY_CHARS
from cloudhelm_tool_gateway.audit import redact_sensitive_text

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.repositories.agent_conversation_repository import AgentConversationRepository
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import AgentRunStatus, TaskStatus
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.subagent_role_policy import (
    ensure_supported_subagent_role,
    normalize_subagent_role,
)
from cloudhelm_platform_api.services.subagent_tool_scope import SubagentToolScope

MAX_SUBAGENT_OBJECTIVE_CHARS = 12000

class SubagentConversationPolicy:
    """集中校验 child 目标、配额、父运行身份和摘要回传。"""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.conversations = AgentConversationRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.tasks = TaskRepository(session)

    @staticmethod
    def normalize_request(
        agent_role: str,
        objective: str,
        expected_result: str,
    ) -> tuple[str, str, str]:
        """只接受当前已实现的只读/分析型 child 角色和有界任务。"""

        role = normalize_subagent_role(agent_role)
        child_objective = objective.strip()
        expected = expected_result.strip()
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

    @staticmethod
    def normalize_summary(summary: str) -> str:
        """只允许简洁、脱敏的最终摘要进入父线程。"""

        normalized = summary.strip()
        if not normalized:
            raise ServiceError(
                "invalid_subagent_summary",
                "子 Agent 最终摘要不能为空。",
                422,
            )
        if len(normalized) > MAX_SUBAGENT_SUMMARY_CHARS:
            raise ServiceError(
                "subagent_summary_too_long",
                "子 Agent 最终摘要不能超过 4000 个字符。",
                422,
            )
        return redact_sensitive_text(normalized) or ""

    def validate_capacity(self, parent: AgentConversation) -> int:
        """校验 child 深度和单 Task active thread 上限。"""

        depth = parent.depth + 1
        if depth > self.settings.agent_max_subagent_depth:
            raise ServiceError(
                "subagent_depth_limit_exceeded",
                "创建子 Agent 失败：超过允许的会话深度。",
                409,
            )
        root = self.conversations.get_root(parent.task_id, for_update=True)
        if root is None:
            raise ServiceError(
                "root_agent_conversation_not_found",
                "创建子 Agent 失败：Task root conversation 不存在。",
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

    def require_running_task(self, task_id: UUID) -> None:
        """锁定 Task，暂停或终态期间不得创建/完成 child。"""

        task = self.tasks.get(task_id, for_update=True)
        if task is None:
            raise ServiceError("task_not_found", "Task 不存在。", 404)
        if task.status != TaskStatus.RUNNING.value:
            raise ServiceError(
                "task_not_running",
                "只有 running Task 可以推进子 Agent 生命周期。",
                409,
            )

    def validate_spawning_run(
        self,
        parent: AgentConversation,
        spawned_by_agent_run_id: UUID,
    ) -> AgentRun:
        """只允许绑定当前父 thread 的同 Task running AgentRun 显式 spawn。"""

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
        if spawning_run.conversation_id != parent.id:
            raise ServiceError(
                "spawning_agent_run_conversation_mismatch",
                "创建子 Agent 失败：父 AgentRun 不属于当前 conversation。",
                409,
            )
        if spawning_run.status != AgentRunStatus.RUNNING.value:
            raise ServiceError(
                "spawning_agent_run_not_running",
                "只有 running AgentRun 可以显式创建子 Agent。",
                409,
            )
        return spawning_run

    def build_child_tool_scope(
        self,
        conversation_id: UUID,
        spawning_run: AgentRun,
        child_role: str,
    ) -> SubagentToolScope:
        """创建 child 时固化父级与 child 工具 allowlist 的交集。"""

        parent_tools, parent_roles = self._resolve_run_permissions(spawning_run)
        child_tools = self._allowed_tools(child_role)
        return SubagentToolScope(
            conversation_id=conversation_id,
            child_role=child_role,
            ancestor_roles=parent_roles,
            effective_allowed_tools=tuple(sorted(parent_tools & child_tools)),
        )

    def resolve_tool_scope(self, agent_run: AgentRun) -> SubagentToolScope | None:
        """解析 subagent AgentRun 的有效工具范围；root AgentRun 返回 ``None``。"""

        if agent_run.conversation_id is None:
            return None
        conversation = self.conversations.get(agent_run.conversation_id)
        if conversation is None:
            raise ServiceError(
                "agent_run_conversation_not_found",
                "AgentRun 绑定的 conversation 不存在。",
                409,
            )
        if conversation.task_id != agent_run.task_id:
            raise ServiceError(
                "agent_run_conversation_task_mismatch",
                "AgentRun 与 conversation 不属于同一 Task。",
                409,
            )
        self.ensure_active(conversation)
        if conversation.source_type == "root":
            return None
        effective_tools, roles = self._resolve_run_permissions(agent_run)
        return SubagentToolScope(
            conversation_id=conversation.id,
            child_role=agent_run.agent_type,
            ancestor_roles=roles[1:],
            effective_allowed_tools=tuple(sorted(effective_tools)),
        )

    def _resolve_run_permissions(
        self,
        agent_run: AgentRun,
    ) -> tuple[set[str], tuple[str, ...]]:
        """沿 conversation lineage 计算当前运行的最小工具权限。"""

        effective_tools = self._allowed_tools(agent_run.agent_type)
        roles = [agent_run.agent_type]
        current_run = agent_run
        visited: set[UUID] = set()

        while current_run.conversation_id is not None:
            conversation = self.conversations.get(current_run.conversation_id)
            if conversation is None:
                raise ServiceError(
                    "agent_run_conversation_not_found",
                    "AgentRun 绑定的 conversation 不存在。",
                    409,
                )
            if conversation.task_id != current_run.task_id:
                raise ServiceError(
                    "agent_run_conversation_task_mismatch",
                    "AgentRun 与 conversation 不属于同一 Task。",
                    409,
                )
            self.ensure_active(conversation)
            if conversation.source_type == "root":
                break
            ensure_supported_subagent_role(current_run.agent_type)
            if conversation.id in visited:
                raise ServiceError(
                    "subagent_conversation_cycle",
                    "子 Agent conversation lineage 存在循环。",
                    409,
                )
            visited.add(conversation.id)
            if conversation.agent_role != current_run.agent_type:
                raise ServiceError(
                    "subagent_agent_run_role_mismatch",
                    "子 AgentRun 角色与 conversation 角色不一致。",
                    409,
                )
            if (
                conversation.spawned_by_agent_run_id is None
                or conversation.parent_conversation_id is None
            ):
                raise ServiceError(
                    "subagent_lineage_incomplete",
                    "子 Agent conversation 缺少父级 lineage。",
                    409,
                )
            parent_run = self.agent_runs.get(conversation.spawned_by_agent_run_id)
            if (
                parent_run is None
                or parent_run.task_id != current_run.task_id
                or parent_run.conversation_id
                != conversation.parent_conversation_id
            ):
                raise ServiceError(
                    "subagent_parent_run_mismatch",
                    "子 Agent conversation 的父 AgentRun 绑定无效。",
                    409,
                )
            effective_tools &= self._allowed_tools(parent_run.agent_type)
            roles.append(parent_run.agent_type)
            current_run = parent_run

        return effective_tools, tuple(roles)

    @staticmethod
    def _allowed_tools(agent_type: str) -> set[str]:
        """读取角色工具矩阵，并把缺失配置转换为稳定业务错误。"""

        try:
            return set(allowed_tools_for(agent_type))
        except ValueError as exc:
            raise ServiceError(
                "agent_tool_policy_missing",
                "Agent 角色缺少工具权限配置。",
                409,
                {"agent_type": agent_type},
            ) from exc

    @staticmethod
    def ensure_active(record: AgentConversation) -> None:
        """终态 conversation 不得继续创建 child 或接收通知。"""

        if record.status != "active":
            raise ServiceError(
                "agent_conversation_not_active",
                "当前 Agent conversation 已结束，不能继续写入。",
                409,
            )
