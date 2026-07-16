"""Celery delivery 到 PostgreSQL claim/handler/terminal 的编排。"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    WorkflowJobEventPayload,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_workflow_engine.config import (
    WorkflowSettings,
)
from cloudhelm_workflow_engine.errors import is_transient_database_error
from cloudhelm_workflow_engine.lease_heartbeat import LeaseHeartbeat
from cloudhelm_workflow_engine.registry import (
    HandlerRegistration,
    HandlerRegistry,
)
from cloudhelm_workflow_engine.schemas import WorkerExecutionResult


class WorkflowWorkerService:
    """使用短 Session 推进一个业务 job，handler 期间不持行锁。"""

    def __init__(
        self,
        *,
        settings: WorkflowSettings,
        session_factory: sessionmaker[Session],
        registry: HandlerRegistry,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.registry = registry

    def execute(
        self,
        *,
        workflow_job_id: UUID,
        worker_owner: str,
    ) -> WorkerExecutionResult:
        """执行一次唯一 delivery owner；重复消息正常 ack/no-op。"""

        claimed = self._claim(workflow_job_id, worker_owner)
        if claimed is None:
            return self._current_result(workflow_job_id, "claim_noop")
        running = self._mark_running(workflow_job_id, worker_owner)
        if running is None:
            return self._current_result(workflow_job_id, "mark_noop")
        deferred = self._nonrunning_result(workflow_job_id, running.status)
        if deferred is not None:
            return deferred
        registration = self._validated_registration(running)
        if registration is None:
            self._resolve_registry_mismatch(
                workflow_job_id,
                worker_owner,
            )
            return self._current_result(
                workflow_job_id,
                "handler_registry_invalid",
            )
        return self._execute_registered_handler(
            workflow_job_id=workflow_job_id,
            worker_owner=worker_owner,
            registration=registration,
        )

    def _execute_registered_handler(
        self,
        *,
        workflow_job_id: UUID,
        worker_owner: str,
        registration: HandlerRegistration,
    ) -> WorkerExecutionResult:
        """在 heartbeat 保护下运行已验证的无外部副作用 handler。"""

        heartbeat = LeaseHeartbeat(
            session_factory=self.session_factory,
            workflow_job_id=workflow_job_id,
            worker_owner=worker_owner,
            lease_seconds=self.settings.job_lease_seconds,
            interval_seconds=self.settings.job_heartbeat_seconds,
        )
        heartbeat.start()
        try:
            job = registration.handler.execute(
                workflow_job_id=workflow_job_id,
                worker_owner=worker_owner,
            )
        except Exception as exc:
            self._schedule_retry(
                workflow_job_id,
                worker_owner,
                (
                    "workflow_database_transient"
                    if is_transient_database_error(exc)
                    else "workflow_handler_execution_failed"
                ),
            )
            return self._current_result(
                workflow_job_id,
                "handler_failed",
            )
        finally:
            heartbeat.stop()
        if job is None:
            return self._current_result(
                workflow_job_id,
                "terminal_noop",
            )
        return WorkerExecutionResult(
            workflow_job_id=workflow_job_id,
            outcome="handled",
            status=job.status,
        )

    @staticmethod
    def _nonrunning_result(
        workflow_job_id: UUID,
        status: str,
    ) -> WorkerExecutionResult | None:
        """把 mark-running 的 pause/terminal 竞争转换为正常 ack 结果。"""

        if status == "running":
            return None
        return WorkerExecutionResult(
            workflow_job_id=workflow_job_id,
            outcome=(
                "task_deferred"
                if status == "pending"
                else "task_cancelled"
            ),
            status=status,
        )

    def _validated_registration(
        self,
        job,
    ) -> HandlerRegistration | None:
        """校验 job/resource/side-effect 与冻结 registry 完全一致。"""

        registration = self.registry.get(job.job_type)
        if (
            registration is None
            or registration.resource_type != job.resource_type
            or registration.side_effect_class != job.side_effect_class
        ):
            return None
        return registration

    def _claim(self, job_id: UUID, owner: str):
        """独立事务 claim。"""

        with self.session_factory() as session:
            job = WorkflowJobRepository(session).claim_job(
                job_id=job_id,
                worker_owner=owner,
                worker_lease=timedelta(
                    seconds=self.settings.job_lease_seconds
                ),
            )
            session.commit()
            return job

    def _mark_running(self, job_id: UUID, owner: str):
        """独立事务 mark-running，并写 Started/Deferred/Cancelled。"""

        with self.session_factory() as session:
            job = WorkflowJobRepository(session).mark_running(
                job_id=job_id,
                worker_owner=owner,
                worker_lease=timedelta(
                    seconds=self.settings.job_lease_seconds
                ),
            )
            if job is not None:
                event_type = {
                    "running": "WorkflowJobStarted",
                    "pending": "WorkflowJobExecutionDeferred",
                    "cancelled": "WorkflowJobCancelled",
                }.get(job.status)
                if event_type is not None:
                    self._record_event(session, event_type, job)
            session.commit()
            return job

    def _resolve_registry_mismatch(
        self,
        job_id: UUID,
        owner: str,
    ) -> None:
        """锁后重验 Task，避免取消/暂停被 registry failure 覆盖。"""

        with self.session_factory() as session:
            job = WorkflowJobRepository(session).resolve_registry_mismatch(
                job_id=job_id,
                worker_owner=owner,
            )
            if job is not None:
                event_type = {
                    "pending": "WorkflowJobExecutionDeferred",
                    "cancelled": "WorkflowJobCancelled",
                    "failed": "WorkflowJobFailed",
                }.get(job.status)
                if event_type is not None:
                    self._record_event(session, event_type, job)
            session.commit()

    def _schedule_retry(
        self,
        job_id: UUID,
        owner: str,
        error_code: str,
    ) -> None:
        """none handler 异常使用 PostgreSQL safe retry，不调用 Celery retry。"""

        with self.session_factory() as session:
            job = WorkflowJobRepository(session).schedule_retry(
                job_id=job_id,
                worker_owner=owner,
                error_code=error_code,
                retry_backoff=timedelta(
                    seconds=self.settings.retry_backoff_seconds
                ),
                max_retry_backoff=timedelta(
                    seconds=self.settings.max_retry_backoff_seconds
                ),
            )
            if job is not None:
                event_type = {
                    "pending": "WorkflowJobRetryScheduled",
                    "cancelled": "WorkflowJobCancelled",
                    "failed": "WorkflowJobFailed",
                    "recovery_required": "WorkflowJobRecoveryRequired",
                }.get(job.status)
                if event_type is not None:
                    self._record_event(session, event_type, job)
            session.commit()

    def _current_result(
        self,
        job_id: UUID,
        outcome: str,
    ) -> WorkerExecutionResult:
        """读取竞争后的当前状态，避免把 no-op 当失败重投。"""

        with self.session_factory() as session:
            job = WorkflowJobRepository(session).get(job_id)
            return WorkerExecutionResult(
                workflow_job_id=job_id,
                outcome=outcome,
                status=job.status if job is not None else None,
            )

    @staticmethod
    def _record_event(
        session: Session,
        event_type: str,
        job,
    ) -> None:
        """记录低敏 WorkflowJob 生命周期事件。"""

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
            "workflow-worker",
            payload,
            job.task_id,
        )
