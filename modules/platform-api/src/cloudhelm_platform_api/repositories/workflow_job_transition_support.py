"""WorkflowJob 状态写入的共享字段与时间顺序辅助。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cloudhelm_platform_api.models.workflow_job import WorkflowJob


def effective_job_time(job: WorkflowJob, database_now: datetime) -> datetime:
    """返回不早于既有审计时间的单次数据库时钟。

    PostgreSQL 行锁等待后使用 `clock_timestamp()`；同时兼容历史测试夹具中
    已存在的未来时间，避免生命周期 CHECK 因时间倒挂掩盖真正的状态竞争。
    """

    candidates = [
        database_now,
        job.created_at,
        job.updated_at,
        job.started_at,
        job.heartbeat_at,
        job.cancel_requested_at,
        job.last_enqueued_at,
    ]
    return max(value for value in candidates if value is not None)


def clear_dispatch_lease(job: WorkflowJob) -> None:
    """清除 dispatcher 临时所有权，不改变 enqueue 审计计数。"""

    job.dispatch_lease_owner = None
    job.dispatch_lease_expires_at = None


def clear_worker_lease(job: WorkflowJob) -> None:
    """清除 worker owner、lease 与 heartbeat。"""

    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def mark_terminal(
    job: WorkflowJob,
    *,
    status: str,
    database_now: datetime,
    error_code: str | None,
    result_json: dict[str, Any] | None,
) -> None:
    """写入 terminal 公共字段并清理所有重投/租约状态。"""

    now = effective_job_time(job, database_now)
    job.status = status
    job.result_json = result_json
    job.error_code = error_code
    job.finished_at = now
    job.next_retry_at = None
    job.next_enqueue_at = None
    clear_worker_lease(job)
    clear_dispatch_lease(job)
    job.updated_at = now


def mark_pending(
    job: WorkflowJob,
    *,
    database_now: datetime,
    next_retry_at: datetime | None,
    next_enqueue_at: datetime,
    error_code: str | None,
) -> None:
    """安全回排 job，并保持数据库 retry/enqueue 不变量。"""

    now = effective_job_time(job, database_now)
    job.status = "pending"
    job.result_json = None
    job.error_code = error_code
    job.finished_at = None
    job.next_retry_at = next_retry_at
    job.next_enqueue_at = next_enqueue_at
    clear_worker_lease(job)
    clear_dispatch_lease(job)
    job.updated_at = now
