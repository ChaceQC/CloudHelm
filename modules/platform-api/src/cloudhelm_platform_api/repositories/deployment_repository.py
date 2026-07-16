"""M7 Deployment 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.deployment import Deployment
from cloudhelm_platform_api.repositories.pagination import fetch_page


class DeploymentRepository:
    """Deployment 表访问对象；不推进状态或触发远端副作用。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, deployment: Deployment) -> Deployment:
        """新增 Deployment 并立即触发数据库约束。"""

        self.session.add(deployment)
        self.session.flush()
        return deployment

    def get(
        self,
        deployment_id: UUID,
        *,
        for_update: bool = False,
    ) -> Deployment | None:
        """按 ID 读取 Deployment，可选加行锁。"""

        return self._one(
            select(Deployment).where(Deployment.id == deployment_id),
            for_update=for_update,
        )

    def get_by_task_idempotency(
        self,
        task_id: UUID,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ) -> Deployment | None:
        """按 Task 与幂等键读取 Deployment。"""

        return self._one(
            select(Deployment).where(
                Deployment.task_id == task_id,
                Deployment.idempotency_key == idempotency_key,
            ),
            for_update=for_update,
        )

    def get_by_environment_release_version(
        self,
        environment_id: UUID,
        release_version: str,
        *,
        for_update: bool = False,
    ) -> Deployment | None:
        """按 Environment 与 release version 读取 Deployment。"""

        return self._one(
            select(Deployment).where(
                Deployment.environment_id == environment_id,
                Deployment.release_version == release_version,
            ),
            for_update=for_update,
        )

    def get_by_remote_operation(
        self,
        remote_target_id: UUID,
        remote_operation_id: str,
        *,
        for_update: bool = False,
    ) -> Deployment | None:
        """按 RemoteTarget 幂等 operation identity 读取 Deployment。"""

        return self._one(
            select(Deployment).where(
                Deployment.remote_target_id == remote_target_id,
                Deployment.remote_operation_id == remote_operation_id,
            ),
            for_update=for_update,
        )

    def latest_by_task(self, task_id: UUID) -> Deployment | None:
        """读取 Task 最新 Deployment 历史。"""

        return self.session.scalar(
            select(Deployment)
            .where(Deployment.task_id == task_id)
            .order_by(
                Deployment.created_at.desc(),
                Deployment.id.desc(),
            )
            .limit(1)
        )

    def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> tuple[list[Deployment], str | None]:
        """按 Project 稳定分页读取 Deployment。"""

        statement: Select[tuple[Deployment]] = select(Deployment).where(
            Deployment.project_id == project_id
        )
        return self._page(statement, limit, cursor, status=status)

    def list_by_environment(
        self,
        environment_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> tuple[list[Deployment], str | None]:
        """按 Environment 稳定分页读取 Deployment。"""

        statement: Select[tuple[Deployment]] = select(Deployment).where(
            Deployment.environment_id == environment_id
        )
        return self._page(statement, limit, cursor, status=status)

    def _one(
        self,
        statement: Select[tuple[Deployment]],
        *,
        for_update: bool,
    ) -> Deployment | None:
        """执行唯一结果查询，并统一行锁刷新语义。"""

        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement.limit(1))

    def _page(
        self,
        statement: Select[tuple[Deployment]],
        limit: int,
        cursor: str | None,
        *,
        status: str | None,
    ) -> tuple[list[Deployment], str | None]:
        """应用可选状态过滤和统一稳定排序。"""

        if status is not None:
            statement = statement.where(Deployment.status == status)
        statement = statement.order_by(
            Deployment.created_at.desc(),
            Deployment.id.desc(),
        )
        return fetch_page(self.session, statement, limit, cursor)
