"""WorkflowJob handler 的统一终态写入与低敏事件记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_transition_support import (
    mark_terminal,
)
from cloudhelm_platform_api.schemas.workflow_job import WorkflowJobEventPayload
from cloudhelm_platform_api.services.event_service import EventService


class WorkflowJobTerminalService:
    """在调用方已持有 Job 锁的事务中写入终态和 EventLog。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = EventService(session)

    def succeed(
        self,
        job: WorkflowJob,
        *,
        database_now: datetime,
        result_json: dict[str, Any],
        outcome: str,
    ) -> WorkflowJob:
        """写入 succeeded、严格结果和可审计 outcome。"""

        mark_terminal(
            job,
            status="succeeded",
            database_now=database_now,
            error_code=None,
            result_json=result_json,
        )
        self._record_event(
            "WorkflowJobSucceeded",
            job,
            extra={"outcome": outcome},
        )
        self.session.flush()
        return job

    def fail(
        self,
        job: WorkflowJob,
        *,
        database_now: datetime,
        error_code: str,
    ) -> WorkflowJob:
        """写入不可重试失败和稳定错误事件。"""

        mark_terminal(
            job,
            status="failed",
            database_now=database_now,
            error_code=error_code,
            result_json=None,
        )
        self._record_event("WorkflowJobFailed", job)
        self.session.flush()
        return job

    def cancel(
        self,
        job: WorkflowJob,
        *,
        database_now: datetime,
        error_code: str = "task_cancelled",
    ) -> WorkflowJob:
        """写入 cancelled，并保留首次取消请求时间。"""

        job.cancel_requested_at = job.cancel_requested_at or database_now
        mark_terminal(
            job,
            status="cancelled",
            database_now=database_now,
            error_code=error_code,
            result_json=None,
        )
        self._record_event("WorkflowJobCancelled", job)
        self.session.flush()
        return job

    def _record_event(
        self,
        event_type: str,
        job: WorkflowJob,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """仅记录 WorkflowJob 生命周期契约允许的低敏字段。"""

        common = WorkflowJobEventPayload(
            workflow_job_id=job.id,
            job_type=job.job_type,
            resource_type=job.resource_type,
            resource_id=job.resource_id,
            status=job.status,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            error_code=job.error_code,
        ).model_dump(mode="json")
        self.events.record(
            event_type,
            "system",
            "workflow-engine",
            {**common, **(extra or {})},
            job.task_id,
        )
