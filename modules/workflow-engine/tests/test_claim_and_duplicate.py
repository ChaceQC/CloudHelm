"""worker claim、重复 delivery 与 pause 竞争测试。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

from sqlalchemy import select

from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)


def test_duplicate_and_concurrent_claim_only_one_owner(
    session_factory,
    seed_job,
) -> None:
    """两个 worker 同时收到同一 message 时 attempt 只增加一次。"""

    refs = seed_job()
    barrier = threading.Barrier(2)

    def claim(owner: str) -> str | None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            job = WorkflowJobRepository(session).claim_job(
                job_id=refs["job_id"],
                worker_owner=owner,
                worker_lease=timedelta(seconds=90),
            )
            session.commit()
            return job.lease_owner if job is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(claim, ("worker:one", "worker:two"))
        )

    assert len([value for value in results if value is not None]) == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(refs["job_id"])
        assert job is not None
        assert job.status == "claimed"
        assert job.attempt == 1
        assert (
            WorkflowJobRepository(session).claim_job(
                job_id=refs["job_id"],
                worker_owner="worker:duplicate",
                worker_lease=timedelta(seconds=90),
            )
            is None
        )


def test_pause_after_claim_returns_pending_without_consuming_attempt(
    session_factory,
    seed_job,
) -> None:
    """pause 在线性化后阻止 handler，并撤销尚未开始的 claim attempt。"""

    refs = seed_job()
    owner = "worker:pause-race"
    with session_factory() as session:
        job = WorkflowJobRepository(session).claim_job(
            job_id=refs["job_id"],
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        session.commit()
        assert job is not None
        assert job.attempt == 1
    with session_factory() as session:
        task = session.get(Task, refs["task_id"])
        assert task is not None
        task.status = "paused"
        session.commit()
    with session_factory() as session:
        job = WorkflowJobRepository(session).mark_running(
            job_id=refs["job_id"],
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        session.commit()

    assert job is not None
    assert job.status == "pending"
    assert job.attempt == 0
    assert job.lease_owner is None
    assert job.next_enqueue_at is not None


def test_future_retry_rejects_old_duplicate_message(
    session_factory,
    seed_job,
) -> None:
    """旧 broker message 不得绕过 PostgreSQL next_retry_at。"""

    refs = seed_job()
    owner = "worker:retry"
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        assert repository.claim_job(
            job_id=refs["job_id"],
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        assert repository.mark_running(
            job_id=refs["job_id"],
            worker_owner=owner,
            worker_lease=timedelta(seconds=90),
        )
        retried = repository.schedule_retry(
            job_id=refs["job_id"],
            worker_owner=owner,
            error_code="transient_test",
            retry_backoff=timedelta(minutes=5),
            max_retry_backoff=timedelta(minutes=5),
        )
        session.commit()
        assert retried is not None
    with session_factory() as session:
        duplicate = WorkflowJobRepository(session).claim_job(
            job_id=refs["job_id"],
            worker_owner="worker:old-message",
            worker_lease=timedelta(seconds=90),
        )
        session.commit()

    assert duplicate is None


def test_cancel_and_claim_race_converges_to_cancelled(
    session_factory,
    seed_job,
) -> None:
    """Task-first claim/cancel 并发只有 cancelled 一个最终结果。"""

    refs = seed_job()
    barrier = threading.Barrier(2)

    def claim() -> bool:
        with session_factory() as session:
            barrier.wait(timeout=10)
            job = WorkflowJobRepository(session).claim_job(
                job_id=refs["job_id"],
                worker_owner="worker:cancel-race",
                worker_lease=timedelta(seconds=90),
            )
            session.commit()
            return job is not None

    def cancel() -> str:
        with session_factory() as session:
            barrier.wait(timeout=10)
            task = session.scalar(
                select(Task)
                .where(Task.id == refs["task_id"])
                .with_for_update()
            )
            assert task is not None
            task.status = "cancelled"
            jobs = WorkflowJobRepository(session).request_cancel(
                task_id=task.id
            )
            session.commit()
            return jobs[0].status if jobs else "no_active_job"

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_future = executor.submit(claim)
        cancelled_future = executor.submit(cancel)
        claimed = claimed_future.result(timeout=15)
        cancel_result = cancelled_future.result(timeout=15)

    assert claimed in {True, False}
    assert cancel_result == "cancelled"
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(refs["job_id"])
        task = session.get(Task, refs["task_id"])
        assert job is not None
        assert task is not None
        assert task.status == "cancelled"
        assert job.status == "cancelled"
        assert job.lease_owner is None
