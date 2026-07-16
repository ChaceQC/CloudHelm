"""M7 ReleaseCandidate 数据访问。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate


class ReleaseCandidateRepository:
    """ReleaseCandidate 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

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
