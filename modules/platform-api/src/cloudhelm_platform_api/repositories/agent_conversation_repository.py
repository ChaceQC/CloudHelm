"""AgentConversation 数据访问。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.agent_conversation import AgentConversation


class AgentConversationRepository:
    """Task root/subagent conversation 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, conversation: AgentConversation) -> AgentConversation:
        """新增会话并刷新数据库约束。"""

        self.session.add(conversation)
        self.session.flush()
        return conversation

    def get(self, conversation_id: UUID, *, for_update: bool = False) -> AgentConversation | None:
        """按 ID 读取会话，可选锁定以串行更新历史。"""

        statement = select(AgentConversation).where(AgentConversation.id == conversation_id)
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def get_root(self, task_id: UUID, *, for_update: bool = False) -> AgentConversation | None:
        """读取 Task 唯一 root conversation。"""

        statement = select(AgentConversation).where(
            AgentConversation.task_id == task_id,
            AgentConversation.source_type == "root",
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def list_children(self, parent_conversation_id: UUID) -> list[AgentConversation]:
        """按创建时间读取直接子会话。"""

        return list(
            self.session.scalars(
                select(AgentConversation)
                .where(
                    AgentConversation.parent_conversation_id
                    == parent_conversation_id
                )
                .order_by(
                    AgentConversation.created_at.asc(),
                    AgentConversation.id.asc(),
                )
            )
        )

    def count_active_subagents(self, task_id: UUID) -> int:
        """统计 Task 下 active child conversations。"""

        count = self.session.scalar(
            select(func.count(AgentConversation.id)).where(
                AgentConversation.task_id == task_id,
                AgentConversation.source_type == "subagent",
                AgentConversation.status == "active",
            )
        )
        return int(count or 0)

    def list_active_by_task(
        self,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> list[AgentConversation]:
        """读取 Task 下全部 active root/child conversations。"""

        statement = (
            select(AgentConversation)
            .where(
                AgentConversation.task_id == task_id,
                AgentConversation.status == "active",
            )
            .order_by(
                AgentConversation.depth.desc(),
                AgentConversation.created_at.asc(),
                AgentConversation.id.asc(),
            )
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return list(self.session.scalars(statement))

    def list_active_descendants(
        self,
        task_id: UUID,
        ancestor_id: UUID,
        *,
        for_update: bool = False,
    ) -> list[AgentConversation]:
        """读取指定 conversation 的全部 active 后代。"""

        active = self.list_active_by_task(task_id, for_update=for_update)
        descendants: list[AgentConversation] = []
        frontier = {ancestor_id}
        while frontier:
            level = [
                record
                for record in active
                if record.parent_conversation_id in frontier
            ]
            if not level:
                break
            descendants.extend(level)
            frontier = {record.id for record in level}
        return descendants
