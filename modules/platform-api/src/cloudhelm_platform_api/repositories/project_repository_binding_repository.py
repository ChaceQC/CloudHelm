"""M7 ProjectRepositoryBinding 数据访问。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)


class ProjectRepositoryBindingRepository:
    """ProjectRepositoryBinding 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_configuration_namespace(self) -> None:
        """串行化 Binding identity 变更，避免跨 Project 并发 swap 死锁。

        PostgreSQL transaction-level advisory lock 只覆盖 RepositoryBinding PUT
        的短事务；读取和 Candidate 流程仍使用实体行锁。
        """

        self.session.execute(
            select(
                func.pg_advisory_xact_lock(
                    0x43484D,
                    0x5245504F,
                )
            )
        ).one()

    def create(
        self,
        binding: ProjectRepositoryBinding,
    ) -> ProjectRepositoryBinding:
        """新增绑定并立即刷新数据库约束。"""

        self.session.add(binding)
        self.session.flush()
        return binding

    def save(
        self,
        binding: ProjectRepositoryBinding,
    ) -> ProjectRepositoryBinding:
        """刷新绑定更新，确保唯一约束在写事件前被裁决。"""

        self.session.add(binding)
        self.session.flush()
        return binding

    def get(
        self,
        binding_id: UUID,
        *,
        for_update: bool = False,
    ) -> ProjectRepositoryBinding | None:
        """按 ID 读取绑定，可选按 Candidate 决策锁序加行锁。"""

        statement = select(ProjectRepositoryBinding).where(
            ProjectRepositoryBinding.id == binding_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def get_by_project(
        self,
        project_id: UUID,
        *,
        for_update: bool = False,
    ) -> ProjectRepositoryBinding | None:
        """按 Project 读取唯一绑定，可选加行锁。"""

        statement = select(ProjectRepositoryBinding).where(
            ProjectRepositoryBinding.project_id == project_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)
