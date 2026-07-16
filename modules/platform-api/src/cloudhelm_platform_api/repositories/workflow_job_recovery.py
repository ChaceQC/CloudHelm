"""WorkflowJob retry、Task lifecycle 与 stale reclaim repository mixin。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_recovery_policy import (
    apply_retry_transition,
    apply_stale_transition,
)
from cloudhelm_platform_api.repositories.workflow_job_transition_support import (
    clear_dispatch_lease,
    effective_job_time,
    mark_pending,
    mark_terminal,
)

_RUNNABLE_TASK_STATUSES = {"running", "waiting_approval"}
_TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}
_LEASE_ACTIVE_STATUSES = {"claimed", "running", "cancel_requested"}


class WorkflowJobRecoveryRepositoryMixin:
    """由 `WorkflowJobRepository` 组合的恢复和 Task 批量状态方法。"""

    session: Any

    def schedule_retry(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        error_code: str,
        retry_backoff: timedelta,
        max_retry_backoff: timedelta,
    ) -> WorkflowJob | None:
        """按 attempt 指数退避；取消或终态 Task 不重新产生 pending。"""

        locked = self._lock_task_and_job(job_id)
        if locked is None:
            return None
        task, job = locked
        database_now = self.database_now()
        if not self._owns_live_lease(
            job,
            worker_owner,
            database_now,
            {"running", "cancel_requested"},
        ):
            return None
        now = effective_job_time(job, database_now)
        apply_retry_transition(
            task_status=task.status,
            job=job,
            now=now,
            error_code=error_code,
            retry_backoff=retry_backoff,
            max_retry_backoff=max_retry_backoff,
        )
        self.session.flush()
        return job

    def request_cancel(
        self,
        *,
        task_id: UUID,
        error_code: str = "task_cancelled",
    ) -> list[WorkflowJob]:
        """Task 已持锁时，按 UUID 顺序取消或请求取消其 active jobs。"""

        jobs = self.list_by_task_for_update(
            task_id,
            statuses=_LEASE_ACTIVE_STATUSES | {"pending"},
        )
        if not jobs:
            return []
        database_now = self.database_now()
        changed: list[WorkflowJob] = []
        for job in jobs:
            now = effective_job_time(job, database_now)
            if job.status in {"pending", "claimed"}:
                job.cancel_requested_at = job.cancel_requested_at or now
                mark_terminal(
                    job,
                    status="cancelled",
                    database_now=now,
                    error_code=error_code,
                    result_json=None,
                )
            elif job.status == "running":
                job.status = "cancel_requested"
                job.cancel_requested_at = job.cancel_requested_at or now
                job.error_code = error_code
                job.updated_at = now
            else:
                continue
            changed.append(job)
        self.session.flush()
        return changed

    def wake_pending_for_task(self, *, task_id: UUID) -> list[WorkflowJob]:
        """Task resume 后唤醒 pending job，但不绕过 future retry。"""

        jobs = self.list_by_task_for_update(task_id, statuses={"pending"})
        if not jobs:
            return []
        database_now = self.database_now()
        for job in jobs:
            job.next_enqueue_at = max(
                database_now,
                job.next_retry_at or database_now,
            )
            job.updated_at = effective_job_time(job, database_now)
        self.session.flush()
        return jobs

    def revoke_dispatch_reservations_for_task(
        self,
        *,
        task_id: UUID,
    ) -> list[WorkflowJob]:
        """Task 已持锁时撤销 pending job token，使旧 finalize 变为 no-op。"""

        jobs = self.list_by_task_for_update(
            task_id,
            statuses={"pending"},
        )
        reserved = [
            job for job in jobs if job.dispatch_lease_owner is not None
        ]
        if not reserved:
            return []
        database_now = self.database_now()
        for job in reserved:
            clear_dispatch_lease(job)
            job.updated_at = effective_job_time(job, database_now)
        self.session.flush()
        return reserved

    def resolve_registry_mismatch(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
    ) -> WorkflowJob | None:
        """Task→Job 重验后把 registry mismatch 收敛为 defer/cancel/fail。"""

        locked = self._lock_task_and_job(job_id)
        if locked is None:
            return None
        task, job = locked
        database_now = self.database_now()
        if not self._owns_live_lease(
            job,
            worker_owner,
            database_now,
            {"running", "cancel_requested"},
        ):
            return None
        now = effective_job_time(job, database_now)
        if (
            job.status == "cancel_requested"
            or task.status in _TERMINAL_TASK_STATUSES
        ):
            job.cancel_requested_at = job.cancel_requested_at or now
            mark_terminal(
                job,
                status="cancelled",
                database_now=now,
                error_code="task_cancelled",
                result_json=None,
            )
        elif task.status not in _RUNNABLE_TASK_STATUSES:
            job.attempt -= 1
            mark_pending(
                job,
                database_now=now,
                next_retry_at=None,
                next_enqueue_at=now,
                error_code="workflow_job_task_paused",
            )
        else:
            mark_terminal(
                job,
                status="failed",
                database_now=now,
                error_code="workflow_handler_registry_mismatch",
                result_json=None,
            )
        self.session.flush()
        return job

    def list_stale_job_ids(self, *, batch_size: int) -> list[UUID]:
        """无锁发现 stale IDs；真正收敛在 Task→Job 的新短事务中完成。"""

        return list(
            self.session.scalars(
                select(WorkflowJob.id)
                .where(
                    WorkflowJob.status.in_(_LEASE_ACTIVE_STATUSES),
                    WorkflowJob.lease_expires_at
                    <= func.clock_timestamp(),
                )
                .order_by(WorkflowJob.lease_expires_at, WorkflowJob.id)
                .limit(batch_size)
            )
        )

    def reclaim_stale_job(
        self,
        *,
        job_id: UUID,
        retry_backoff: timedelta,
        max_retry_backoff: timedelta,
    ) -> WorkflowJob | None:
        """按 Task→Job 锁序回收一个 stale attempt。"""

        locked = self._lock_task_and_job(job_id)
        if locked is None:
            return None
        task, job = locked
        database_now = self.database_now()
        if (
            job.status not in _LEASE_ACTIVE_STATUSES
            or job.lease_expires_at is None
            or job.lease_expires_at > database_now
        ):
            return None
        now = effective_job_time(job, database_now)
        apply_stale_transition(
            task_status=task.status,
            job=job,
            now=now,
            retry_backoff=retry_backoff,
            max_retry_backoff=max_retry_backoff,
        )
        self.session.flush()
        return job
