"""WorkflowJob stale lease 的纯状态收敛策略。"""

from __future__ import annotations

from datetime import datetime, timedelta

from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.workflow_job_transition_support import (
    clear_dispatch_lease,
    effective_job_time,
    mark_pending,
    mark_terminal,
)

_TERMINAL_TASK_STATUSES = {"done", "failed", "cancelled"}


def apply_retry_transition(
    *,
    task_status: str,
    job: WorkflowJob,
    now: datetime,
    error_code: str,
    retry_backoff: timedelta,
    max_retry_backoff: timedelta,
) -> None:
    """将 handler 异常收敛为取消、失败、重试或人工恢复。"""

    if job.side_effect_class != "none":
        mark_recovery_required(job, now)
        return
    if (
        job.status == "cancel_requested"
        or task_status in _TERMINAL_TASK_STATUSES
    ):
        job.cancel_requested_at = job.cancel_requested_at or now
        mark_terminal(
            job,
            status="cancelled",
            database_now=now,
            error_code="task_cancelled",
            result_json=None,
        )
        return
    if job.attempt >= job.max_attempts:
        mark_terminal(
            job,
            status="failed",
            database_now=now,
            error_code="workflow_job_attempts_exhausted",
            result_json=None,
        )
        return
    delay = _exponential_backoff(
        retry_backoff,
        max_retry_backoff,
        exponent=max(job.attempt - 1, 0),
    )
    retry_at = now + delay
    mark_pending(
        job,
        database_now=now,
        next_retry_at=retry_at,
        next_enqueue_at=retry_at,
        error_code=error_code,
    )


def apply_stale_transition(
    *,
    task_status: str,
    job: WorkflowJob,
    now: datetime,
    retry_backoff: timedelta,
    max_retry_backoff: timedelta,
) -> None:
    """按执行起点、副作用分类、取消和 attempt 顺序收敛 stale job。

    `claimed` 表示 handler 尚未开始，因此可按 Task/attempt 安全收敛。外部
    handler 一旦进入 running/cancel_requested，本切片没有 resolver，未知远端
    状态必须 fail closed 到 recovery_required，不能用 Task 终态或 attempt 耗尽
    推断远端副作用已经取消或失败。
    """

    if job.status == "claimed":
        _apply_safe_transition(
            task_status=task_status,
            job=job,
            now=now,
            retry_backoff=retry_backoff,
            max_retry_backoff=max_retry_backoff,
        )
        return
    if job.side_effect_class != "none":
        mark_recovery_required(job, now)
        return
    _apply_safe_transition(
        task_status=task_status,
        job=job,
        now=now,
        retry_backoff=retry_backoff,
        max_retry_backoff=max_retry_backoff,
    )


def _apply_safe_transition(
    *,
    task_status: str,
    job: WorkflowJob,
    now: datetime,
    retry_backoff: timedelta,
    max_retry_backoff: timedelta,
) -> None:
    """收敛无外部副作用或尚未开始 handler 的 stale job。"""

    if (
        job.status == "cancel_requested"
        or task_status in _TERMINAL_TASK_STATUSES
    ):
        job.cancel_requested_at = job.cancel_requested_at or now
        mark_terminal(
            job,
            status="cancelled",
            database_now=now,
            error_code="task_cancelled",
            result_json=None,
        )
        return
    if job.attempt >= job.max_attempts:
        mark_terminal(
            job,
            status="failed",
            database_now=now,
            error_code="workflow_job_attempts_exhausted",
            result_json=None,
        )
        return
    delay = _exponential_backoff(
        retry_backoff,
        max_retry_backoff,
        exponent=max(job.attempt - 1, 0),
    )
    retry_at = now + delay
    mark_pending(
        job,
        database_now=now,
        next_retry_at=retry_at,
        next_enqueue_at=retry_at,
        error_code="workflow_job_worker_lease_expired",
    )


def mark_recovery_required(job: WorkflowJob, now: datetime) -> None:
    """把未知外部状态转为人工阻塞态并清理自动执行入口。"""

    job.status = "recovery_required"
    job.result_json = None
    job.error_code = "workflow_external_state_unknown"
    job.finished_at = None
    job.next_retry_at = None
    job.next_enqueue_at = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    clear_dispatch_lease(job)
    job.updated_at = effective_job_time(job, now)


def _exponential_backoff(
    initial: timedelta,
    maximum: timedelta,
    *,
    exponent: int,
) -> timedelta:
    """计算无 jitter、可复现且封顶的退避。"""

    seconds = min(
        maximum.total_seconds(),
        initial.total_seconds() * (2**exponent),
    )
    return timedelta(seconds=seconds)
