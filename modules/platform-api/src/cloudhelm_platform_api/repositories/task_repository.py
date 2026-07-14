"""Task 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.pagination import fetch_page


class TaskRepository:
    """Task 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, task: Task) -> Task:
        """新增 Task 并刷新主键。"""

        self.session.add(task)
        self.session.flush()
        return task

    def get(self, task_id: UUID, *, for_update: bool = False) -> Task | None:
        """按 ID 读取 Task，可选加行锁用于短事务步骤抢占。"""

        if not for_update:
            return self.session.get(Task, task_id)
        return self.session.scalar(
            select(Task)
            .where(Task.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def list(
        self,
        limit: int,
        cursor: str | None,
        project_id: UUID | None = None,
    ) -> tuple[list[Task], str | None]:
        """分页读取 Task，可按 Project 过滤。"""

        statement: Select[tuple[Task]] = select(Task).order_by(Task.created_at.desc(), Task.id.desc())
        if project_id is not None:
            statement = statement.where(Task.project_id == project_id)
        return fetch_page(self.session, statement, limit, cursor)
