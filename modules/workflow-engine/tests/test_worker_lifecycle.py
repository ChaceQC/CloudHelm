"""heartbeat、terminal、Task cancel 与 stale reclaim 测试。"""

from datetime import UTC, datetime, timedelta
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.workflow_job_recovery_policy import (
    apply_stale_transition,
)
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_workflow_engine.config import WorkflowSettings
from cloudhelm_workflow_engine.lease_heartbeat import LeaseHeartbeat
from cloudhelm_workflow_engine.stale_reclaimer import StaleReclaimer


def _claim_and_run(
    session_factory,
    job_id,
    *,
    owner: str,
    lease: timedelta,
):
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        claimed = repository.claim_job(
            job_id=job_id,
            worker_owner=owner,
            worker_lease=lease,
        )
        running = repository.mark_running(
            job_id=job_id,
            worker_owner=owner,
            worker_lease=lease,
        )
        session.commit()
        assert claimed is not None
        assert running is not None
        return running


def test_heartbeat_and_old_owner_finish_are_guarded(
    session_factory,
    seed_job,
) -> None:
    """只有当前 owner 可 heartbeat/finish。"""

    refs = seed_job()
    owner = "worker:current"
    _claim_and_run(
        session_factory,
        refs["job_id"],
        owner=owner,
        lease=timedelta(seconds=90),
    )

    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        assert (
            repository.heartbeat(
                job_id=refs["job_id"],
                worker_owner="worker:old",
                worker_lease=timedelta(seconds=90),
            )
            is None
        )
        assert repository.heartbeat(
            job_id=refs["job_id"],
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        assert (
            repository.finish_succeeded(
                job_id=refs["job_id"],
                worker_owner="worker:old",
                result_json={"outcome": "invalid-owner"},
            )
            is None
        )
        finished = repository.finish_succeeded(
            job_id=refs["job_id"],
            worker_owner=owner,
            result_json={"outcome": "valid"},
        )
        session.commit()
    assert finished is not None
    assert finished.status == "succeeded"
    assert finished.lease_owner is None


def test_heartbeat_thread_extends_current_owner_lease(
    session_factory,
    seed_job,
) -> None:
    """真实 heartbeat thread 使用独立短 Session 延长当前 owner lease。"""

    refs = seed_job()
    owner = "worker:heartbeat-thread"
    running = _claim_and_run(
        session_factory,
        refs["job_id"],
        owner=owner,
        lease=timedelta(seconds=6),
    )
    original_expiry = running.lease_expires_at
    heartbeat = LeaseHeartbeat(
        session_factory=session_factory,
        workflow_job_id=refs["job_id"],
        worker_owner=owner,
        lease_seconds=10,
        interval_seconds=1,
    )

    heartbeat.start()
    deadline = time.monotonic() + 5
    extended_expiry = None
    try:
        while time.monotonic() < deadline:
            with session_factory() as session:
                job = WorkflowJobRepository(session).get(refs["job_id"])
                assert job is not None
                if (
                    job.lease_expires_at is not None
                    and original_expiry is not None
                    and job.lease_expires_at > original_expiry
                ):
                    extended_expiry = job.lease_expires_at
                    break
            time.sleep(0.1)
    finally:
        heartbeat.stop()

    assert heartbeat.lease_lost is False
    assert extended_expiry is not None


def test_expired_lease_heartbeat_is_rejected(
    session_factory,
    seed_job,
) -> None:
    """过期 owner 的 heartbeat 不能复活 stale attempt。"""

    refs = seed_job()
    _claim_and_run(
        session_factory,
        refs["job_id"],
        owner="worker:expired-heartbeat",
        lease=timedelta(milliseconds=30),
    )
    time.sleep(0.06)
    heartbeat = LeaseHeartbeat(
        session_factory=session_factory,
        workflow_job_id=refs["job_id"],
        worker_owner="worker:expired-heartbeat",
        lease_seconds=3,
        interval_seconds=1,
    )

    assert heartbeat.tick_once() is False
    assert heartbeat.lease_lost is True


def test_stale_running_none_job_is_requeued(
    session_factory,
    seed_job,
) -> None:
    """worker hard crash 后 none job 按 lease 安全回排。"""

    refs = seed_job()
    _claim_and_run(
        session_factory,
        refs["job_id"],
        owner="worker:crash",
        lease=timedelta(milliseconds=30),
    )
    time.sleep(0.06)
    result = StaleReclaimer(
        settings=WorkflowSettings(),
        session_factory=session_factory,
    ).run_once()

    assert result.reclaimed == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(refs["job_id"])
        assert job is not None
        assert job.status == "pending"
        assert job.error_code == "workflow_job_worker_lease_expired"
        assert job.next_retry_at == job.next_enqueue_at


def test_stale_claimed_job_is_requeued_before_handler_start(
    session_factory,
    seed_job,
) -> None:
    """claimed 表示 handler 未开始，worker 崩溃后可按 attempt 安全回排。"""

    references = seed_job()
    with session_factory() as session:
        claimed = WorkflowJobRepository(session).claim_job(
            job_id=references["job_id"],
            worker_owner="worker:claimed-crash",
            worker_lease=timedelta(milliseconds=30),
        )
        session.commit()
        assert claimed is not None
        assert claimed.status == "claimed"
    time.sleep(0.06)

    result = StaleReclaimer(
        settings=WorkflowSettings(),
        session_factory=session_factory,
    ).run_once()

    assert result.reclaimed == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(references["job_id"])
        event = session.scalar(
            select(EventLog).where(
                EventLog.task_id == references["task_id"],
                EventLog.event_type == "WorkflowJobRetryScheduled",
            )
        )
        assert job is not None
        assert job.status == "pending"
        assert job.attempt == 1
        assert event is not None


def test_stale_last_attempt_fails_exhausted(
    session_factory,
    seed_job,
) -> None:
    """达到 max_attempts 的 stale attempt 不再重放。"""

    refs = seed_job(max_attempts=1)
    _claim_and_run(
        session_factory,
        refs["job_id"],
        owner="worker:last-attempt",
        lease=timedelta(milliseconds=30),
    )
    time.sleep(0.06)
    result = StaleReclaimer(
        settings=WorkflowSettings(),
        session_factory=session_factory,
    ).run_once()

    assert result.failed == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(refs["job_id"])
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "workflow_job_attempts_exhausted"


def test_stale_cancel_requested_job_finishes_cancelled(
    session_factory,
    seed_job,
) -> None:
    """none handler 的 cancel_requested lease 过期后安全收敛为 cancelled。"""

    references = seed_job()
    _claim_and_run(
        session_factory,
        references["job_id"],
        owner="worker:cancel-crash",
        lease=timedelta(milliseconds=100),
    )
    with session_factory() as session:
        task = session.get(Task, references["task_id"])
        assert task is not None
        task.status = "cancelled"
        changed = WorkflowJobRepository(session).request_cancel(
            task_id=references["task_id"]
        )
        session.commit()
        assert changed[0].status == "cancel_requested"
    time.sleep(0.14)

    result = StaleReclaimer(
        settings=WorkflowSettings(),
        session_factory=session_factory,
    ).run_once()

    assert result.cancelled == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(references["job_id"])
        event = session.scalar(
            select(EventLog).where(
                EventLog.task_id == references["task_id"],
                EventLog.event_type == "WorkflowJobCancelled",
            )
        )
        assert job is not None
        assert job.status == "cancelled"
        assert event is not None


@pytest.mark.parametrize(
    "side_effect_class",
    ("external_idempotent", "external_uncertain"),
)
@pytest.mark.parametrize("status", ("running", "cancel_requested"))
def test_external_stale_unknown_requires_manual_recovery(
    side_effect_class: str,
    status: str,
) -> None:
    """无 resolver 时外部 running/取消未知状态不得按 Task/attempt 猜测终态。"""

    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=status,
        side_effect_class=side_effect_class,
        attempt=3,
        max_attempts=3,
        created_at=now,
        updated_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=(now if status == "cancel_requested" else None),
        last_enqueued_at=None,
        result_json=None,
        error_code="task_cancelled",
        finished_at=None,
        next_retry_at=None,
        next_enqueue_at=None,
        lease_owner="worker:external",
        lease_expires_at=now,
        dispatch_lease_owner=None,
        dispatch_lease_expires_at=None,
    )

    apply_stale_transition(
        task_status="cancelled",
        job=job,
        now=now,
        retry_backoff=timedelta(seconds=1),
        max_retry_backoff=timedelta(seconds=60),
    )

    assert job.status == "recovery_required"
    assert job.error_code == "workflow_external_state_unknown"
    assert job.finished_at is None
    assert job.next_retry_at is None
    assert job.next_enqueue_at is None
    assert job.lease_owner is None


def test_recovery_required_is_not_automatically_replayed(
    session_factory,
    seed_job,
) -> None:
    """人工阻塞态不进入 dispatcher、claim 或 stale reclaimer。"""

    references = seed_job()
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        job = repository.get(references["job_id"], for_update=True)
        assert job is not None
        job.status = "recovery_required"
        job.error_code = "workflow_external_state_unknown"
        job.next_retry_at = None
        job.next_enqueue_at = None
        session.commit()

    result = StaleReclaimer(
        settings=WorkflowSettings(),
        session_factory=session_factory,
    ).run_once()
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        reservations = repository.reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:manual-block",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )
        claimed = repository.claim_job(
            job_id=references["job_id"],
            worker_owner="worker:manual-block",
            worker_lease=timedelta(seconds=90),
        )
        session.commit()

    assert result.scanned == 0
    assert reservations == []
    assert claimed is None


def test_task_cancel_pending_and_running_jobs(
    session_factory,
    seed_job,
) -> None:
    """Task cancel 直接取消 pending，并把 running 转 cancel_requested。"""

    pending_refs = seed_job()
    running_refs = seed_job()
    _claim_and_run(
        session_factory,
        running_refs["job_id"],
        owner="worker:running",
        lease=timedelta(seconds=90),
    )
    with session_factory() as session:
        pending_task = session.get(Task, pending_refs["task_id"])
        running_task = session.get(Task, running_refs["task_id"])
        assert pending_task is not None
        assert running_task is not None
        pending_task.status = "cancelled"
        running_task.status = "cancelled"
        pending_jobs = WorkflowJobRepository(session).request_cancel(
            task_id=pending_refs["task_id"]
        )
        running_jobs = WorkflowJobRepository(session).request_cancel(
            task_id=running_refs["task_id"]
        )
        session.commit()

    assert pending_jobs[0].status == "cancelled"
    assert running_jobs[0].status == "cancel_requested"
    assert running_jobs[0].lease_owner == "worker:running"

    with session_factory() as session:
        cancelled = WorkflowJobRepository(session).finish_cancelled(
            job_id=running_refs["job_id"],
            worker_owner="worker:running",
        )
        session.commit()
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.lease_owner is None


def test_reclaimer_forever_survives_single_cycle_error(
    session_factory,
    monkeypatch,
) -> None:
    """单次数据库异常不终止常驻 stale reclaimer。"""

    reclaimer = StaleReclaimer(
        settings=WorkflowSettings(),
        session_factory=session_factory,
    )
    state = {"stopped": False, "calls": 0}

    class StopEvent:
        def is_set(self) -> bool:
            return state["stopped"]

        def wait(self, _timeout: float) -> bool:
            return state["stopped"]

    def flaky_cycle():
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("temporary reclaimer failure")
        state["stopped"] = True

    monkeypatch.setattr(reclaimer, "run_once", flaky_cycle)

    reclaimer.run_forever(StopEvent())

    assert state["calls"] == 2
