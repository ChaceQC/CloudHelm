"""M7 PostgreSQL 权威 WorkflowJob 聚合 repository。"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_dispatch import (
    DispatchReservation,
    WorkflowJobDispatchRepositoryMixin,
)
from cloudhelm_platform_api.repositories.workflow_job_lifecycle import (
    WorkflowJobLifecycleRepositoryMixin,
)
from cloudhelm_platform_api.repositories.workflow_job_recovery import (
    WorkflowJobRecoveryRepositoryMixin,
)


class WorkflowJobRepository(
    WorkflowJobDispatchRepositoryMixin,
    WorkflowJobLifecycleRepositoryMixin,
    WorkflowJobRecoveryRepositoryMixin,
):
    """组合 dispatch、worker lifecycle 与 recovery 的数据访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, job: WorkflowJob) -> WorkflowJob:
        """新增 WorkflowJob 并刷新主键和数据库约束。"""

        self.session.add(job)
        self.session.flush()
        return job

    def get(
        self,
        job_id: UUID,
        *,
        for_update: bool = False,
    ) -> WorkflowJob | None:
        """按 ID 读取 job，可选加锁用于短事务状态迁移。"""

        statement = select(WorkflowJob).where(WorkflowJob.id == job_id)
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def get_by_resource(
        self,
        *,
        job_type: str,
        resource_type: str,
        resource_id: UUID,
        for_update: bool = False,
    ) -> WorkflowJob | None:
        """按 handler 与领域资源读取最新 reconcile job。"""

        statement = (
            select(WorkflowJob)
            .where(
                WorkflowJob.job_type == job_type,
                WorkflowJob.resource_type == resource_type,
                WorkflowJob.resource_id == resource_id,
            )
            .order_by(
                WorkflowJob.created_at.desc(),
                WorkflowJob.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def database_now(self) -> datetime:
        """读取会随语句推进的 PostgreSQL `clock_timestamp()`。"""

        value = self.session.scalar(select(func.clock_timestamp()))
        assert value is not None
        return value

    def list_by_task_for_update(
        self,
        task_id: UUID,
        *,
        statuses: Collection[str] | None = None,
    ) -> list[WorkflowJob]:
        """按 UUID 顺序锁定 Task 的 jobs，供生命周期批量处理。"""

        statement = select(WorkflowJob).where(
            WorkflowJob.task_id == task_id
        )
        if statuses is not None:
            statement = statement.where(WorkflowJob.status.in_(statuses))
        return list(
            self.session.scalars(
                statement.order_by(WorkflowJob.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )


__all__ = ["DispatchReservation", "WorkflowJobRepository"]
