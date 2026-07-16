"""WorkflowJob worker、Task 生命周期与 stale reclaim repository mixin。"""

from __future__ import annotations

from collections.abc import Collection
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_transition_support import (
    clear_dispatch_lease,
    effective_job_time,
    mark_pending,
    mark_terminal,
)

_RUNNABLE_TASK_STATUSES = {"running", "waiting_approval"}
_TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}
_LEASE_ACTIVE_STATUSES = {"claimed", "running", "cancel_requested"}


class WorkflowJobLifecycleRepositoryMixin:
    """由 `WorkflowJobRepository` 组合的短事务状态方法。"""

    session: Any

    def claim_job(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        worker_lease: timedelta,
    ) -> WorkflowJob | None:
        """按 Task→Job 锁序抢占 due pending job。"""

        locked = self._lock_task_and_job(job_id)
        if locked is None:
            return None
        task, job = locked
        database_now = self.database_now()
        if (
            task.status not in _RUNNABLE_TASK_STATUSES
            or job.status != "pending"
            or job.attempt >= job.max_attempts
            or (
                job.next_retry_at is not None
                and job.next_retry_at > database_now
            )
        ):
            return None
        now = effective_job_time(job, database_now)
        job.attempt += 1
        job.status = "claimed"
        job.lease_owner = worker_owner
        job.heartbeat_at = now
        job.lease_expires_at = now + worker_lease
        job.next_retry_at = None
        job.next_enqueue_at = None
        job.result_json = None
        job.error_code = None
        job.last_enqueue_error_code = None
        clear_dispatch_lease(job)
        job.updated_at = now
        self.session.flush()
        return job

    def mark_running(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        worker_lease: timedelta,
    ) -> WorkflowJob | None:
        """在独立事务重验 Task 后进入 running 或撤销未开始 claim。"""

        locked = self._lock_task_and_job(job_id)
        if locked is None:
            return None
        task, job = locked
        database_now = self.database_now()
        if not self._owns_live_lease(job, worker_owner, database_now, {"claimed"}):
            return None
        now = effective_job_time(job, database_now)
        if task.status in _RUNNABLE_TASK_STATUSES:
            job.status = "running"
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.lease_expires_at = now + worker_lease
            job.updated_at = now
        elif task.status in _TERMINAL_TASK_STATUSES:
            job.cancel_requested_at = max(now, job.created_at)
            mark_terminal(
                job,
                status="cancelled",
                database_now=now,
                error_code="workflow_job_task_terminal",
                result_json=None,
            )
        else:
            # handler 尚未开始，用户暂停/阶段竞争不消耗业务 attempt。
            job.attempt -= 1
            mark_pending(
                job,
                database_now=now,
                next_retry_at=None,
                next_enqueue_at=now,
                error_code="workflow_job_task_paused",
            )
        self.session.flush()
        return job

    def heartbeat(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        worker_lease: timedelta,
    ) -> WorkflowJob | None:
        """仅允许当前未过期 owner 延长 active lease。"""

        job = self.get(job_id, for_update=True)
        if job is None:
            return None
        database_now = self.database_now()
        if not self._owns_live_lease(
            job,
            worker_owner,
            database_now,
            _LEASE_ACTIVE_STATUSES,
        ):
            return None
        now = effective_job_time(job, database_now)
        job.heartbeat_at = now
        job.lease_expires_at = now + worker_lease
        job.updated_at = now
        self.session.flush()
        return job

    def finish_succeeded(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        result_json: dict[str, Any],
    ) -> WorkflowJob | None:
        """写入当前 attempt 的真实成功结果；旧 owner 晚到时 no-op。"""

        return self._finish(
            job_id=job_id,
            worker_owner=worker_owner,
            status="succeeded",
            error_code=None,
            result_json=result_json,
        )

    def finish_failed(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        error_code: str,
    ) -> WorkflowJob | None:
        """写入不可重试业务失败。"""

        return self._finish(
            job_id=job_id,
            worker_owner=worker_owner,
            status="failed",
            error_code=error_code,
            result_json=None,
        )

    def finish_cancelled(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        error_code: str = "workflow_job_cancelled",
    ) -> WorkflowJob | None:
        """把当前 owner 的 cancel_requested job 收敛为 cancelled。"""

        job = self.get(job_id, for_update=True)
        if job is None:
            return None
        database_now = self.database_now()
        if not self._owns_live_lease(
            job,
            worker_owner,
            database_now,
            {"cancel_requested"},
        ):
            return None
        now = effective_job_time(job, database_now)
        job.cancel_requested_at = job.cancel_requested_at or now
        mark_terminal(
            job,
            status="cancelled",
            database_now=now,
            error_code=error_code,
            result_json=None,
        )
        self.session.flush()
        return job

    def _finish(
        self,
        *,
        job_id: UUID,
        worker_owner: str,
        status: str,
        error_code: str | None,
        result_json: dict[str, Any] | None,
    ) -> WorkflowJob | None:
        """共享 succeeded/failed owner、lease 和 terminal 写入。"""

        job = self.get(job_id, for_update=True)
        if job is None:
            return None
        database_now = self.database_now()
        if not self._owns_live_lease(
            job,
            worker_owner,
            database_now,
            {"running", "cancel_requested"},
        ):
            return None
        mark_terminal(
            job,
            status=status,
            database_now=database_now,
            error_code=error_code,
            result_json=result_json,
        )
        self.session.flush()
        return job

    def _lock_task_and_job(
        self,
        job_id: UUID,
    ) -> tuple[Task, WorkflowJob] | None:
        """先读 task hint，再按 Task→WorkflowJob 获取规定行锁。"""

        task_id = self.session.scalar(
            select(WorkflowJob.task_id).where(WorkflowJob.id == job_id)
        )
        if task_id is None:
            return None
        task = self.session.scalar(
            select(Task)
            .where(Task.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = self.get(job_id, for_update=True)
        if task is None or job is None or job.task_id != task.id:
            return None
        return task, job

    @staticmethod
    def _owns_live_lease(
        job: WorkflowJob,
        worker_owner: str,
        database_now,
        statuses: Collection[str],
    ) -> bool:
        """校验 owner、active 状态和未过期 lease。"""

        return (
            job.status in statuses
            and job.lease_owner == worker_owner
            and job.lease_expires_at is not None
            and job.lease_expires_at > database_now
        )
