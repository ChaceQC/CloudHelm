"""`release_candidate_reconcile` 独立事务适配器。"""

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_platform_api.services.release_candidate_reconcile_service import (
    ReleaseCandidateReconcileService,
)


class ReleaseCandidateReconcileHandler:
    """调用 Platform API persistence service 并原子提交 reconcile。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def execute(
        self,
        *,
        workflow_job_id: UUID,
        worker_owner: str,
    ):
        """使用新 Session 写 Candidate/Approval/job/event 同一事务。"""

        with self.session_factory() as session:
            try:
                job = ReleaseCandidateReconcileService(session).execute(
                    workflow_job_id=workflow_job_id,
                    worker_owner=worker_owner,
                )
                session.commit()
                return job
            except Exception:
                session.rollback()
                raise
