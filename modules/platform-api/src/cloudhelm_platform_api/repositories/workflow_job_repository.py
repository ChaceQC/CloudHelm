"""M7 WorkflowJob 数据访问。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.workflow_job import WorkflowJob


class WorkflowJobRepository:
    """PostgreSQL 权威 WorkflowJob 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, job: WorkflowJob) -> WorkflowJob:
        """新增 WorkflowJob 并刷新主键和数据库约束。"""

        self.session.add(job)
        self.session.flush()
        return job

    def get_by_resource(
        self,
        *,
        job_type: str,
        resource_type: str,
        resource_id: UUID,
        for_update: bool = False,
    ) -> WorkflowJob | None:
        """按 handler 与领域资源读取唯一 reconcile job。"""

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
