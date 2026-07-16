"""M6 PullRequestRecord 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.repositories.pagination import fetch_page


class PullRequestRecordRepository:
    """PullRequestRecord 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, record: PullRequestRecord) -> PullRequestRecord:
        """新增本地等价 PR record 并刷新数据库约束。"""

        self.session.add(record)
        self.session.flush()
        return record

    def get(self, record_id: UUID) -> PullRequestRecord | None:
        """按 ID 读取 PR record。"""

        return self.session.get(PullRequestRecord, record_id)

    def get_by_task_commit(
        self,
        task_id: UUID,
        commit_sha: str,
    ) -> PullRequestRecord | None:
        """按任务和最终 commit SHA 读取等价 PR record。"""

        return self.session.scalar(
            select(PullRequestRecord)
            .where(
                PullRequestRecord.task_id == task_id,
                PullRequestRecord.commit_sha == commit_sha,
            )
            .limit(1)
        )

    def get_by_task_idempotency_key(
        self,
        task_id: UUID,
        idempotency_key: str,
    ) -> PullRequestRecord | None:
        """按任务内幂等键读取等价 PR record。"""

        return self.session.scalar(
            select(PullRequestRecord)
            .where(
                PullRequestRecord.task_id == task_id,
                PullRequestRecord.idempotency_key == idempotency_key,
            )
            .limit(1)
        )

    def latest_by_task(
        self,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> PullRequestRecord | None:
        """读取任务最新 PR record，可选加锁后更新其生命周期。"""

        statement = (
            select(PullRequestRecord)
            .where(PullRequestRecord.task_id == task_id)
            .order_by(
                PullRequestRecord.created_at.desc(),
                PullRequestRecord.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def latest_open_by_task(
        self,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> PullRequestRecord | None:
        """读取任务最新 open PR，可选锁定其不可变来源证据。"""

        statement = (
            select(PullRequestRecord)
            .where(
                PullRequestRecord.task_id == task_id,
                PullRequestRecord.status == "open",
            )
            .order_by(
                PullRequestRecord.created_at.desc(),
                PullRequestRecord.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def latest_open_by_task_for_update(
        self,
        task_id: UUID,
    ) -> PullRequestRecord | None:
        """锁定任务最新 open PR，供 Candidate 创建流程复用。"""

        return self.latest_open_by_task(task_id, for_update=True)

    def latest_by_task_and_plan(
        self,
        task_id: UUID,
        development_plan_id: UUID,
        recipe_sha256: str,
    ) -> PullRequestRecord | None:
        """读取当前 plan/recipe 且四类门禁证据仍可用的最新 PR record。"""

        diff_artifact = aliased(Artifact, name="pr_diff_artifact")
        test_artifact = aliased(Artifact, name="pr_test_artifact")
        review_artifact = aliased(Artifact, name="pr_review_artifact")
        security_artifact = aliased(Artifact, name="pr_security_artifact")
        artifacts = (
            diff_artifact,
            test_artifact,
            review_artifact,
            security_artifact,
        )
        return self.session.scalar(
            select(PullRequestRecord)
            .join(
                diff_artifact,
                PullRequestRecord.diff_artifact_id == diff_artifact.id,
            )
            .join(
                test_artifact,
                PullRequestRecord.test_artifact_id == test_artifact.id,
            )
            .join(
                review_artifact,
                PullRequestRecord.review_artifact_id == review_artifact.id,
            )
            .join(
                security_artifact,
                PullRequestRecord.security_artifact_id
                == security_artifact.id,
            )
            .where(
                PullRequestRecord.task_id == task_id,
                PullRequestRecord.development_plan_id
                == development_plan_id,
                *(
                    condition
                    for artifact in artifacts
                    for condition in (
                        artifact.status == "available",
                        artifact.metadata_json[
                            "development_plan_id"
                        ].astext
                        == str(development_plan_id),
                        artifact.metadata_json["recipe_sha256"].astext
                        == recipe_sha256,
                    )
                ),
            )
            .order_by(
                PullRequestRecord.created_at.desc(),
                PullRequestRecord.id.desc(),
            )
            .limit(1)
        )

    def list_by_task(
        self,
        task_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> tuple[list[PullRequestRecord], str | None]:
        """分页读取任务 PR record，可按状态过滤。"""

        statement: Select[tuple[PullRequestRecord]] = (
            select(PullRequestRecord)
            .where(PullRequestRecord.task_id == task_id)
            .order_by(
                PullRequestRecord.created_at.desc(),
                PullRequestRecord.id.desc(),
            )
        )
        if status is not None:
            statement = statement.where(PullRequestRecord.status == status)
        return fetch_page(self.session, statement, limit, cursor)
