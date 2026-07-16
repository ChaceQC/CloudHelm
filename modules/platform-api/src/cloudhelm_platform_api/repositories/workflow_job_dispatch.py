"""WorkflowJob durable dispatcher 的 reserve 与 finalize 短事务。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_transition_support import (
    clear_dispatch_lease,
    effective_job_time,
)

_RUNNABLE_TASK_STATUSES = ("running", "waiting_approval")


@dataclass(frozen=True)
class DispatchReservation:
    """一次 dispatcher reserve 后允许 publish 的不可变 token。"""

    workflow_job_id: UUID
    enqueue_attempt: int
    dispatch_owner: str


class WorkflowJobDispatchRepositoryMixin:
    """由 `WorkflowJobRepository` 组合的 durable dispatch 方法。"""

    session: Any

    def reserve_due_jobs(
        self,
        *,
        dispatch_owner_prefix: str,
        dispatch_lease: timedelta,
        batch_size: int,
    ) -> list[DispatchReservation]:
        """先锁 Task 再锁 due job；调用方提交后才可访问 broker。"""

        due_cutoff = self.database_now()
        candidate_rows = self._list_due_candidate_rows(
            due_cutoff=due_cutoff,
            scan_limit=max(batch_size * 4, batch_size),
        )
        locked_task_ids = self._lock_candidate_tasks(
            candidate_rows=candidate_rows,
            batch_size=batch_size,
        )
        if not locked_task_ids:
            return []
        jobs = self._lock_due_jobs(
            task_ids=locked_task_ids,
            due_cutoff=due_cutoff,
            batch_size=batch_size,
        )
        return self._reserve_jobs(
            jobs=jobs,
            dispatch_owner_prefix=dispatch_owner_prefix,
            dispatch_lease=dispatch_lease,
        )

    def _list_due_candidate_rows(
        self,
        *,
        due_cutoff: datetime,
        scan_limit: int,
    ) -> list[Any]:
        """无锁读取少量候选 identity，真正状态在取得 Task 锁后重验。"""

        return list(
            self.session.execute(
                select(WorkflowJob.task_id, WorkflowJob.id)
                .join(Task, Task.id == WorkflowJob.task_id)
                .where(
                    Task.status.in_(_RUNNABLE_TASK_STATUSES),
                    *self._due_conditions(due_cutoff),
                )
                .order_by(
                    WorkflowJob.next_enqueue_at,
                    WorkflowJob.id,
                )
                .limit(scan_limit)
            )
        )

    def _lock_candidate_tasks(
        self,
        *,
        candidate_rows: list[Any],
        batch_size: int,
    ) -> list[UUID]:
        """按候选顺序锁定足以填充 batch 的 runnable Task。"""

        candidate_counts = Counter(row.task_id for row in candidate_rows)
        task_ids = list(
            dict.fromkeys(row.task_id for row in candidate_rows)
        )
        locked_task_ids: list[UUID] = []
        reserved_capacity = 0
        for task_id in task_ids:
            locked_task_id = self.session.scalar(
                select(Task.id)
                .where(
                    Task.id == task_id,
                    Task.status.in_(_RUNNABLE_TASK_STATUSES),
                )
                .with_for_update(skip_locked=True)
            )
            if locked_task_id is None:
                continue
            locked_task_ids.append(locked_task_id)
            reserved_capacity += candidate_counts[locked_task_id]
            if reserved_capacity >= batch_size:
                break
        return locked_task_ids

    def _lock_due_jobs(
        self,
        *,
        task_ids: list[UUID],
        due_cutoff: datetime,
        batch_size: int,
    ) -> list[WorkflowJob]:
        """Task 锁后按稳定顺序锁定并重验 due WorkflowJob。"""

        return list(
            self.session.scalars(
                select(WorkflowJob)
                .where(
                    WorkflowJob.task_id.in_(task_ids),
                    *self._due_conditions(due_cutoff),
                )
                .order_by(
                    WorkflowJob.next_enqueue_at,
                    WorkflowJob.id,
                )
                .limit(batch_size)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        )

    def _reserve_jobs(
        self,
        *,
        jobs: list[WorkflowJob],
        dispatch_owner_prefix: str,
        dispatch_lease: timedelta,
    ) -> list[DispatchReservation]:
        """为锁定 jobs 生成逐条唯一 token 并写 dispatch lease。"""

        if not jobs:
            return []
        reserved_at = self.database_now()
        reservations: list[DispatchReservation] = []
        for job in jobs:
            now = effective_job_time(job, reserved_at)
            dispatch_owner = f"{dispatch_owner_prefix}:{uuid4()}"
            job.dispatch_lease_owner = dispatch_owner
            job.dispatch_lease_expires_at = now + dispatch_lease
            job.enqueue_attempt += 1
            job.updated_at = now
            reservations.append(
                DispatchReservation(
                    workflow_job_id=job.id,
                    enqueue_attempt=job.enqueue_attempt,
                    dispatch_owner=dispatch_owner,
                )
            )
        self.session.flush()
        return reservations

    def finalize_dispatch_success(
        self,
        *,
        job_id: UUID,
        dispatch_owner: str,
        expected_enqueue_attempt: int,
        redispatch_after: timedelta,
    ) -> WorkflowJob | None:
        """确认 publish；worker 先 claim 或 owner 已更换时保持 no-op。"""

        job = self.get(job_id, for_update=True)
        if not self._owns_dispatch_reservation(
            job,
            dispatch_owner=dispatch_owner,
            expected_enqueue_attempt=expected_enqueue_attempt,
        ):
            return None
        database_now = self.database_now()
        assert job is not None
        now = effective_job_time(job, database_now)
        job.last_enqueued_at = now
        job.next_enqueue_at = now + redispatch_after
        job.last_enqueue_error_code = None
        clear_dispatch_lease(job)
        job.updated_at = now
        self.session.flush()
        return job

    def finalize_dispatch_failure(
        self,
        *,
        job_id: UUID,
        dispatch_owner: str,
        expected_enqueue_attempt: int,
        error_code: str,
        enqueue_backoff: timedelta,
        max_enqueue_backoff: timedelta,
    ) -> WorkflowJob | None:
        """记录 broker failure 并安排有界补投。"""

        job = self.get(job_id, for_update=True)
        if not self._owns_dispatch_reservation(
            job,
            dispatch_owner=dispatch_owner,
            expected_enqueue_attempt=expected_enqueue_attempt,
        ):
            return None
        database_now = self.database_now()
        assert job is not None
        now = effective_job_time(job, database_now)
        delay_seconds = min(
            max_enqueue_backoff.total_seconds(),
            enqueue_backoff.total_seconds()
            * (2 ** max(job.enqueue_attempt - 1, 0)),
        )
        job.next_enqueue_at = now + timedelta(seconds=delay_seconds)
        job.last_enqueue_error_code = error_code
        clear_dispatch_lease(job)
        job.updated_at = now
        self.session.flush()
        return job

    @staticmethod
    def _due_conditions(due_cutoff: datetime) -> tuple:
        """返回 reserve 初筛与锁后重验共用的 due 条件。"""

        return (
            WorkflowJob.status == "pending",
            WorkflowJob.attempt < WorkflowJob.max_attempts,
            or_(
                WorkflowJob.next_retry_at.is_(None),
                WorkflowJob.next_retry_at <= due_cutoff,
            ),
            WorkflowJob.next_enqueue_at <= due_cutoff,
            or_(
                WorkflowJob.dispatch_lease_expires_at.is_(None),
                WorkflowJob.dispatch_lease_expires_at <= due_cutoff,
            ),
        )

    @staticmethod
    def _owns_dispatch_reservation(
        job: WorkflowJob | None,
        *,
        dispatch_owner: str,
        expected_enqueue_attempt: int,
    ) -> bool:
        """防止旧 dispatcher finalize 覆盖新 reserve 或 worker claim。"""

        return (
            job is not None
            and job.status == "pending"
            and job.dispatch_lease_owner == dispatch_owner
            and job.enqueue_attempt == expected_enqueue_attempt
        )
