"""M7 ReleaseCandidate 数据访问。"""

from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate


class ReleaseCandidateRepository:
    """ReleaseCandidate 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, candidate: ReleaseCandidate) -> ReleaseCandidate:
        """新增 Candidate 并立即刷新数据库唯一约束。"""

        self.session.add(candidate)
        self.session.flush()
        return candidate

    def get(
        self,
        candidate_id: UUID,
        *,
        for_update: bool = False,
    ) -> ReleaseCandidate | None:
        """按 ID 读取 Candidate，可选加行锁。"""

        statement = select(ReleaseCandidate).where(
            ReleaseCandidate.id == candidate_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    def get_by_approval_id(
        self,
        approval_id: UUID,
    ) -> ReleaseCandidate | None:
        """按第一道审批读取 Candidate hint。"""

        return self.session.scalar(
            select(ReleaseCandidate)
            .where(ReleaseCandidate.approval_id == approval_id)
            .limit(1)
        )

    def get_by_pr_snapshot_for_update(
        self,
        pull_request_record_id: UUID,
        binding_snapshot_sha256: str,
    ) -> ReleaseCandidate | None:
        """锁定同一 PR 与 binding snapshot 的幂等 Candidate。"""

        return self.session.scalar(
            select(ReleaseCandidate)
            .where(
                ReleaseCandidate.pull_request_record_id
                == pull_request_record_id,
                ReleaseCandidate.binding_snapshot_sha256
                == binding_snapshot_sha256,
            )
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def get_active_by_task_for_update(
        self,
        task_id: UUID,
    ) -> ReleaseCandidate | None:
        """锁定 Task 当前 pending/approved Candidate。"""

        return self.session.scalar(
            select(ReleaseCandidate)
            .where(
                ReleaseCandidate.task_id == task_id,
                ReleaseCandidate.status.in_(
                    ("pending_approval", "approved")
                ),
            )
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def latest_by_task(
        self,
        task_id: UUID,
    ) -> ReleaseCandidate | None:
        """优先读取 active Candidate，否则返回最新历史记录。"""

        active_priority = case(
            (
                ReleaseCandidate.status.in_(
                    ("pending_approval", "approved")
                ),
                0,
            ),
            else_=1,
        )
        return self.session.scalar(
            select(ReleaseCandidate)
            .where(ReleaseCandidate.task_id == task_id)
            .order_by(
                active_priority,
                ReleaseCandidate.created_at.desc(),
                ReleaseCandidate.id.desc(),
            )
            .limit(1)
        )

    def list_active_by_binding_for_update(
        self,
        repository_binding_id: UUID,
    ) -> list[ReleaseCandidate]:
        """按 UUID 顺序锁定绑定下尚可推进的 Candidate。"""

        return list(
            self.session.scalars(
                select(ReleaseCandidate)
                .where(
                    ReleaseCandidate.repository_binding_id
                    == repository_binding_id,
                    ReleaseCandidate.status.in_(
                        ("pending_approval", "approved")
                    ),
                )
                .order_by(ReleaseCandidate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
