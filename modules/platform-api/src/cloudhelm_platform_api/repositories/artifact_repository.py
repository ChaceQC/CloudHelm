"""M6 Artifact 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.repositories.pagination import fetch_page


class ArtifactRepository:
    """Artifact 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, artifact: Artifact) -> Artifact:
        """新增 Artifact 并刷新数据库约束。"""

        self.session.add(artifact)
        self.session.flush()
        return artifact

    def get(self, artifact_id: UUID) -> Artifact | None:
        """按 ID 读取 Artifact。"""

        return self.session.get(Artifact, artifact_id)

    def get_by_task_idempotency_key(
        self,
        task_id: UUID,
        idempotency_key: str,
    ) -> Artifact | None:
        """读取任务内已由同一幂等键创建的 Artifact。"""

        return self.session.scalar(
            select(Artifact)
            .where(
                Artifact.task_id == task_id,
                Artifact.idempotency_key == idempotency_key,
            )
            .limit(1)
        )

    def latest_by_task_and_type(
        self,
        task_id: UUID,
        artifact_type: str,
        *,
        status: str | None = None,
    ) -> Artifact | None:
        """读取任务指定类型的最新 Artifact。"""

        statement = select(Artifact).where(
            Artifact.task_id == task_id,
            Artifact.artifact_type == artifact_type,
        )
        if status is not None:
            statement = statement.where(Artifact.status == status)
        return self.session.scalar(
            statement.order_by(
                Artifact.created_at.desc(),
                Artifact.id.desc(),
            ).limit(1)
        )

    def latest_by_task_type_and_execution_context(
        self,
        task_id: UUID,
        artifact_type: str,
        *,
        development_plan_id: UUID,
        recipe_sha256: str,
        status: str | None = None,
    ) -> Artifact | None:
        """读取当前 DevelopmentPlan/recipe 对应类型的最新 Artifact。"""

        statement = select(Artifact).where(
            Artifact.task_id == task_id,
            Artifact.artifact_type == artifact_type,
            Artifact.metadata_json["development_plan_id"].astext
            == str(development_plan_id),
            Artifact.metadata_json["recipe_sha256"].astext == recipe_sha256,
        )
        if status is not None:
            statement = statement.where(Artifact.status == status)
        return self.session.scalar(
            statement.order_by(
                Artifact.created_at.desc(),
                Artifact.id.desc(),
            ).limit(1)
        )

    def list_by_task(
        self,
        task_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        artifact_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Artifact], str | None]:
        """分页读取任务 Artifact，可按类型和状态过滤。"""

        statement: Select[tuple[Artifact]] = (
            select(Artifact)
            .where(Artifact.task_id == task_id)
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        if artifact_type is not None:
            statement = statement.where(Artifact.artifact_type == artifact_type)
        if status is not None:
            statement = statement.where(Artifact.status == status)
        return fetch_page(self.session, statement, limit, cursor)
