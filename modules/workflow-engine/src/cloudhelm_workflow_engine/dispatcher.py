"""PostgreSQL due scan、dispatch lease 与 Celery publish 补偿。"""

from __future__ import annotations

import logging
import os
import socket
import threading
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    WorkflowJobEventPayload,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_workflow_engine.broker import CeleryBrokerPublisher
from cloudhelm_workflow_engine.config import WorkflowSettings
from cloudhelm_workflow_engine.schemas import DispatchCycleResult

LOGGER = logging.getLogger(__name__)


class WorkflowDispatcher:
    """周期扫描 PostgreSQL，提交 reserve 后再访问 Redis。"""

    def __init__(
        self,
        *,
        settings: WorkflowSettings,
        session_factory: sessionmaker[Session],
        publisher: CeleryBrokerPublisher,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.publisher = publisher

    def run_once(self) -> DispatchCycleResult:
        """执行一次 reserve、publish 与逐条 finalize。"""

        owner_prefix = (
            f"dispatcher:{socket.gethostname()}:{os.getpid()}:{uuid4()}"
        )
        with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            reservations = repository.reserve_due_jobs(
                dispatch_owner_prefix=owner_prefix,
                dispatch_lease=timedelta(
                    seconds=self.settings.dispatch_lease_seconds
                ),
                batch_size=self.settings.batch_size,
            )
            session.commit()
        outcomes = self.publisher.publish_batch(reservations)
        published = 0
        deferred = 0
        for outcome in outcomes:
            if outcome.succeeded:
                published += 1
                self._finalize_success(outcome.reservation)
            else:
                deferred += 1
                self._finalize_failure(
                    outcome.reservation,
                    outcome.error_code
                    or "workflow_broker_publish_failed",
                )
        return DispatchCycleResult(
            reserved=len(reservations),
            published=published,
            deferred=deferred,
        )

    def run_forever(self, stop_event: threading.Event) -> None:
        """运行到 stop_event；单周期异常记录后继续，等待可被 SIGTERM 打断。"""

        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                LOGGER.exception("Workflow dispatcher 周期执行失败。")
            stop_event.wait(self.settings.dispatch_interval_seconds)

    def _finalize_success(self, reservation) -> None:
        """使用新短 Session 确认 publish success。"""

        with self.session_factory() as session:
            WorkflowJobRepository(session).finalize_dispatch_success(
                job_id=reservation.workflow_job_id,
                dispatch_owner=reservation.dispatch_owner,
                expected_enqueue_attempt=reservation.enqueue_attempt,
                redispatch_after=timedelta(
                    seconds=self.settings.redispatch_after_seconds
                ),
            )
            session.commit()

    def _finalize_failure(
        self,
        reservation,
        error_code: str,
    ) -> None:
        """写入 broker error、退避时间和低敏 deferred 事件。"""

        with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            job = repository.finalize_dispatch_failure(
                job_id=reservation.workflow_job_id,
                dispatch_owner=reservation.dispatch_owner,
                expected_enqueue_attempt=reservation.enqueue_attempt,
                error_code=error_code,
                enqueue_backoff=timedelta(
                    seconds=self.settings.enqueue_backoff_seconds
                ),
                max_enqueue_backoff=timedelta(
                    seconds=self.settings.max_enqueue_backoff_seconds
                ),
            )
            if job is not None:
                payload = WorkflowJobEventPayload(
                    workflow_job_id=job.id,
                    job_type=job.job_type,
                    resource_type=job.resource_type,
                    resource_id=job.resource_id,
                    status=job.status,
                    attempt=job.attempt,
                    max_attempts=job.max_attempts,
                    error_code=error_code,
                ).model_dump(mode="json")
                EventService(session).record(
                    "WorkflowJobDispatchDeferred",
                    "system",
                    "workflow-dispatcher",
                    payload,
                    job.task_id,
                )
            session.commit()
