"""不依赖 Redis 的 PostgreSQL stale lease 回收进程。"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    WorkflowJobEventPayload,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_workflow_engine.config import WorkflowSettings
from cloudhelm_workflow_engine.schemas import ReclaimBatchResult

LOGGER = logging.getLogger(__name__)


class StaleReclaimer:
    """无锁扫描 ID，再按 Task→Job 在独立短事务重验并收敛。"""

    def __init__(
        self,
        *,
        settings: WorkflowSettings,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def run_once(self) -> ReclaimBatchResult:
        """回收一批 stale attempts。"""

        with self.session_factory() as session:
            job_ids = WorkflowJobRepository(session).list_stale_job_ids(
                batch_size=self.settings.batch_size
            )
        counts = {
            "reclaimed": 0,
            "cancelled": 0,
            "failed": 0,
            "recovery_required": 0,
        }
        for job_id in job_ids:
            with self.session_factory() as session:
                job = WorkflowJobRepository(session).reclaim_stale_job(
                    job_id=job_id,
                    retry_backoff=timedelta(
                        seconds=self.settings.retry_backoff_seconds
                    ),
                    max_retry_backoff=timedelta(
                        seconds=self.settings.max_retry_backoff_seconds
                    ),
                )
                if job is not None:
                    self._record_transition(session, job)
                    if job.status == "pending":
                        counts["reclaimed"] += 1
                    elif job.status in counts:
                        counts[job.status] += 1
                session.commit()
        return ReclaimBatchResult(
            scanned=len(job_ids),
            reclaimed=counts["reclaimed"],
            cancelled=counts["cancelled"],
            failed=counts["failed"],
            recovery_required=counts["recovery_required"],
        )

    def run_forever(self, stop_event: threading.Event) -> None:
        """周期回收；单周期异常记录后继续，不依赖 maintenance queue。"""

        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                LOGGER.exception("Workflow stale reclaimer 周期执行失败。")
            stop_event.wait(self.settings.reclaim_interval_seconds)

    @staticmethod
    def _record_transition(session: Session, job) -> None:
        """按收敛状态写精确事件。"""

        event_types = {
            "pending": "WorkflowJobRetryScheduled",
            "cancelled": "WorkflowJobCancelled",
            "failed": "WorkflowJobFailed",
            "recovery_required": "WorkflowJobRecoveryRequired",
        }
        event_type = event_types.get(job.status)
        if event_type is None:
            return
        payload = WorkflowJobEventPayload(
            workflow_job_id=job.id,
            job_type=job.job_type,
            resource_type=job.resource_type,
            resource_id=job.resource_id,
            status=job.status,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            error_code=job.error_code,
        ).model_dump(mode="json")
        EventService(session).record(
            event_type,
            "system",
            "workflow-reclaimer",
            payload,
            job.task_id,
        )
