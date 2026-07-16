"""M7 CIRun 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.ci_run import CIRun
from cloudhelm_platform_api.repositories.pagination import fetch_page


class CIRunRepository:
    """CIRun 表访问对象；只负责查询、持久化、分页和行锁。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, ci_run: CIRun) -> CIRun:
        """新增 CIRun 并立即触发数据库约束。"""

        self.session.add(ci_run)
        self.session.flush()
        return ci_run

    def get(
        self,
        ci_run_id: UUID,
        *,
        for_update: bool = False,
    ) -> CIRun | None:
        """按 ID 读取 CIRun，可选加行锁。"""

        return self._one(
            select(CIRun).where(CIRun.id == ci_run_id),
            for_update=for_update,
        )

    def get_by_candidate(
        self,
        candidate_id: UUID,
        *,
        for_update: bool = False,
    ) -> CIRun | None:
        """按唯一 ReleaseCandidate 读取 CIRun。"""

        return self._one(
            select(CIRun).where(
                CIRun.release_candidate_id == candidate_id
            ),
            for_update=for_update,
        )

    def get_by_task_idempotency(
        self,
        task_id: UUID,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ) -> CIRun | None:
        """按 Task 与幂等键读取 CIRun。"""

        return self._one(
            select(CIRun).where(
                CIRun.task_id == task_id,
                CIRun.idempotency_key == idempotency_key,
            ),
            for_update=for_update,
        )

    def get_by_external_run(
        self,
        provider: str,
        repository_external_id: str,
        external_run_id: str,
        *,
        for_update: bool = False,
    ) -> CIRun | None:
        """按 provider 稳定 run identity 读取 CIRun。"""

        return self._one(
            select(CIRun).where(
                CIRun.provider == provider,
                CIRun.repository_external_id == repository_external_id,
                CIRun.external_run_id == external_run_id,
            ),
            for_update=for_update,
        )

    def list_by_task(
        self,
        task_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> tuple[list[CIRun], str | None]:
        """按 Task 稳定分页读取 CIRun。"""

        statement: Select[tuple[CIRun]] = select(CIRun).where(
            CIRun.task_id == task_id
        )
        return self._page(statement, limit, cursor, status=status)

    def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> tuple[list[CIRun], str | None]:
        """按 Project 稳定分页读取 CIRun。"""

        statement: Select[tuple[CIRun]] = select(CIRun).where(
            CIRun.project_id == project_id
        )
        return self._page(statement, limit, cursor, status=status)

    def _one(
        self,
        statement: Select[tuple[CIRun]],
        *,
        for_update: bool,
    ) -> CIRun | None:
        """执行唯一结果查询，并统一行锁刷新语义。"""

        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement.limit(1))

    def _page(
        self,
        statement: Select[tuple[CIRun]],
        limit: int,
        cursor: str | None,
        *,
        status: str | None,
    ) -> tuple[list[CIRun], str | None]:
        """应用可选状态过滤和统一稳定排序。"""

        if status is not None:
            statement = statement.where(CIRun.status == status)
        statement = statement.order_by(
            CIRun.created_at.desc(),
            CIRun.id.desc(),
        )
        return fetch_page(self.session, statement, limit, cursor)
