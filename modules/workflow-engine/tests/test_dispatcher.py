"""Durable dispatcher 与 publish finalize 测试。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import time
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_workflow_engine.config import WorkflowSettings
from cloudhelm_workflow_engine.dispatcher import WorkflowDispatcher
from cloudhelm_workflow_engine.schemas import PublishOutcome


class RecordingPublisher:
    """测试 publisher：记录 reservation 并返回指定错误。"""

    def __init__(self, error_code: str | None = None) -> None:
        self.error_code = error_code
        self.reservations = []

    def publish_batch(self, reservations):
        self.reservations = list(reservations)
        return [
            PublishOutcome(
                reservation=reservation,
                error_code=self.error_code,
            )
            for reservation in reservations
        ]


class ImmediateStopEvent:
    """不真实等待的 run_forever 测试 stop event。"""

    def __init__(self) -> None:
        self.stopped = False

    def is_set(self) -> bool:
        """返回循环停止状态。"""

        return self.stopped

    def wait(self, _timeout: float) -> bool:
        """跳过真实 sleep。"""

        return self.stopped


def test_reserve_filters_paused_task_and_orders_due_jobs(
    session_factory,
    seed_job,
) -> None:
    """dispatcher 只选 runnable Task 的 due pending job。"""

    first = seed_job()
    second = seed_job(task_status="paused")

    with session_factory() as session:
        reservations = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:cycle-1",
            dispatch_lease=timedelta(seconds=15),
            batch_size=50,
        )
        session.commit()

    assert [item.workflow_job_id for item in reservations] == [
        first["job_id"]
    ]
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        reserved = repository.get(first["job_id"])
        paused = repository.get(second["job_id"])
        assert reserved is not None
        assert paused is not None
        assert reserved.enqueue_attempt == 1
        assert reserved.dispatch_lease_owner == reservations[0].dispatch_owner
        assert reservations[0].dispatch_owner.startswith(
            "dispatcher:cycle-1:"
        )
        assert paused.enqueue_attempt == 0
        assert paused.dispatch_lease_owner is None


def test_batch_reservations_use_unique_dispatch_tokens(
    session_factory,
    seed_job,
) -> None:
    """同一 dispatcher cycle 内每个 job 也必须使用独立 reservation token。"""

    references = [seed_job() for _ in range(2)]
    with session_factory() as session:
        reservations = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:batch",
            dispatch_lease=timedelta(seconds=15),
            batch_size=2,
        )
        session.commit()

    owners = [item.dispatch_owner for item in reservations]
    assert len(owners) == 2
    assert len(set(owners)) == 2
    with session_factory() as session:
        stored_owners = {
            WorkflowJobRepository(session)
            .get(reference["job_id"])
            .dispatch_lease_owner
            for reference in references
        }
    assert stored_owners == set(owners)


def test_pause_lock_wins_dispatch_reservation_race(
    session_factory,
    seed_job,
) -> None:
    """pause 已持 Task 锁时，dispatcher 跳过该 Task 而不产生 reservation。"""

    references = seed_job()
    pause_locked = Event()
    allow_pause_commit = Event()

    def pause_transaction() -> None:
        with session_factory() as session:
            task = (
                session.query(Task)
                .filter(Task.id == references["task_id"])
                .with_for_update()
                .one()
            )
            task.status = "paused"
            pause_locked.set()
            assert allow_pause_commit.wait(timeout=5)
            session.commit()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pause_transaction)
        assert pause_locked.wait(timeout=5)
        try:
            with session_factory() as session:
                reservations = WorkflowJobRepository(
                    session
                ).reserve_due_jobs(
                    dispatch_owner_prefix="dispatcher:pause-race",
                    dispatch_lease=timedelta(seconds=15),
                    batch_size=1,
                )
                session.commit()
        finally:
            allow_pause_commit.set()
        future.result(timeout=5)

    assert reservations == []
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(references["job_id"])
        task = session.get(Task, references["task_id"])
        assert job is not None
        assert task is not None
        assert task.status == "paused"
        assert job.enqueue_attempt == 0
        assert job.dispatch_lease_owner is None


def test_pause_revokes_token_before_resume_and_old_finalize(
    platform_client,
    session_factory,
    seed_job,
) -> None:
    """pause 返回后旧 publish finalize 不得覆盖 resume 的立即补投时间。"""

    references = seed_job()
    with session_factory() as session:
        reservation = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:late-finalize",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )[0]
        session.commit()

    paused = platform_client.post(
        f"/api/tasks/{references['task_id']}/pause",
        json={"actor_id": "pytest"},
    )
    assert paused.status_code == 200, paused.text
    resumed = platform_client.post(
        f"/api/tasks/{references['task_id']}/resume",
        json={"actor_id": "pytest"},
    )
    assert resumed.status_code == 200, resumed.text
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        before = repository.get(references["job_id"])
        assert before is not None
        resume_enqueue_at = before.next_enqueue_at
        finalized = repository.finalize_dispatch_success(
            job_id=references["job_id"],
            dispatch_owner=reservation.dispatch_owner,
            expected_enqueue_attempt=reservation.enqueue_attempt,
            redispatch_after=timedelta(seconds=60),
        )
        session.commit()
        after = repository.get(references["job_id"])

    assert finalized is None
    assert after is not None
    assert after.dispatch_lease_owner is None
    assert after.next_enqueue_at == resume_enqueue_at
    with session_factory() as session:
        next_reservations = WorkflowJobRepository(
            session
        ).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:after-resume",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )
        session.commit()
    assert len(next_reservations) == 1
    assert next_reservations[0].dispatch_owner != reservation.dispatch_owner


def test_finalize_requires_owner_and_expected_enqueue_attempt(
    session_factory,
    seed_job,
) -> None:
    """旧 finalize 不覆盖新 reservation。"""

    refs = seed_job()
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        reservation = repository.reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:new",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )[0]
        session.commit()

    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        assert (
            repository.finalize_dispatch_success(
                job_id=refs["job_id"],
                dispatch_owner="dispatcher:old",
                expected_enqueue_attempt=reservation.enqueue_attempt,
                redispatch_after=timedelta(seconds=60),
            )
            is None
        )
        assert (
            repository.finalize_dispatch_success(
                job_id=refs["job_id"],
                dispatch_owner=reservation.dispatch_owner,
                expected_enqueue_attempt=reservation.enqueue_attempt + 1,
                redispatch_after=timedelta(seconds=60),
            )
            is None
        )
        job = repository.finalize_dispatch_success(
            job_id=refs["job_id"],
            dispatch_owner=reservation.dispatch_owner,
            expected_enqueue_attempt=reservation.enqueue_attempt,
            redispatch_after=timedelta(seconds=60),
        )
        session.commit()
        assert job is not None
        assert job.last_enqueued_at is not None
        assert job.next_enqueue_at > job.last_enqueued_at
        assert job.dispatch_lease_owner is None


def test_dispatcher_records_broker_failure_and_backoff(
    session_factory,
    seed_job,
) -> None:
    """Redis failure 保持 PostgreSQL pending 并写 deferred 事件。"""

    refs = seed_job()
    publisher = RecordingPublisher("workflow_broker_unavailable")
    dispatcher = WorkflowDispatcher(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        publisher=publisher,
    )

    result = dispatcher.run_once()

    assert result.reserved == 1
    assert result.published == 0
    assert result.deferred == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(refs["job_id"])
        event = session.query(EventLog).filter_by(
            event_type="WorkflowJobDispatchDeferred"
        ).one()
        assert job is not None
        assert job.status == "pending"
        assert job.last_enqueue_error_code == "workflow_broker_unavailable"
        assert event.payload["workflow_job_id"] == str(refs["job_id"])


def test_worker_claim_before_old_finalize_makes_finalize_noop(
    session_factory,
    seed_job,
) -> None:
    """publish 后 worker 可先 claim，旧 dispatcher finalize 不回退状态。"""

    refs = seed_job()
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        reservation = repository.reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:race",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )[0]
        session.commit()
    with session_factory() as session:
        claimed = WorkflowJobRepository(session).claim_job(
            job_id=refs["job_id"],
            worker_owner="worker:delivery-1",
            worker_lease=timedelta(seconds=90),
        )
        session.commit()
        assert claimed is not None
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        finalized = repository.finalize_dispatch_success(
            job_id=refs["job_id"],
            dispatch_owner=reservation.dispatch_owner,
            expected_enqueue_attempt=reservation.enqueue_attempt,
            redispatch_after=timedelta(seconds=60),
        )
        session.commit()
        assert finalized is None
        job = repository.get(refs["job_id"])
        assert job is not None
        assert job.status == "claimed"


def test_reserve_crash_before_publish_recovers_after_dispatch_lease(
    session_factory,
    seed_job,
) -> None:
    """reserve 已提交、publish 前崩溃时 lease 到期后可再次补投。"""

    refs = seed_job()
    with session_factory() as session:
        first = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:crashed",
            dispatch_lease=timedelta(milliseconds=30),
            batch_size=1,
        )
        session.commit()
        assert len(first) == 1
    time.sleep(0.06)
    with session_factory() as session:
        second = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:recovered",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )
        session.commit()

    assert len(second) == 1
    assert second[0].workflow_job_id == refs["job_id"]
    assert second[0].enqueue_attempt == 2


def test_reserve_skips_locked_job_and_honors_batch_order(
    session_factory,
    seed_job,
) -> None:
    """并发 dispatcher 使用 SKIP LOCKED，不阻塞且按 UUID 稳定补齐 batch。"""

    references = [seed_job() for _ in range(3)]
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        same_due_at = repository.database_now()
        for reference in references:
            job = repository.get(reference["job_id"], for_update=True)
            assert job is not None
            job.next_enqueue_at = same_due_at
        session.commit()

    first_session = session_factory()
    try:
        first = WorkflowJobRepository(first_session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:holding-lock",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )
        assert len(first) == 1
        with session_factory() as second_session:
            second = WorkflowJobRepository(
                second_session
            ).reserve_due_jobs(
                dispatch_owner_prefix="dispatcher:skip-locked",
                dispatch_lease=timedelta(seconds=15),
                batch_size=2,
            )
            second_session.commit()
    finally:
        first_session.rollback()
        first_session.close()

    expected_ids = sorted(
        (reference["job_id"] for reference in references),
        key=lambda value: value.int,
    )
    assert first[0].workflow_job_id == expected_ids[0]
    assert [item.workflow_job_id for item in second] == expected_ids[1:]


def test_reserve_filters_future_enqueue_and_terminal_task(
    session_factory,
    seed_job,
) -> None:
    """future enqueue 与终态 Task 不进入本轮 reservation。"""

    due = seed_job()
    future = seed_job()
    terminal = seed_job(task_status="done")
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        job = repository.get(future["job_id"], for_update=True)
        assert job is not None
        job.next_enqueue_at = repository.database_now() + timedelta(
            minutes=5
        )
        session.commit()
    with session_factory() as session:
        reservations = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:filter",
            dispatch_lease=timedelta(seconds=15),
            batch_size=10,
        )
        session.commit()

    assert [item.workflow_job_id for item in reservations] == [
        due["job_id"]
    ]
    assert future["job_id"] not in {
        item.workflow_job_id for item in reservations
    }
    assert terminal["job_id"] not in {
        item.workflow_job_id for item in reservations
    }


def test_dispatcher_forever_survives_single_cycle_error(
    session_factory,
    monkeypatch,
) -> None:
    """数据库周期异常只记录一次，不终止常驻 dispatcher。"""

    dispatcher = WorkflowDispatcher(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        publisher=RecordingPublisher(),
    )
    stop_event = ImmediateStopEvent()
    calls = 0

    def flaky_cycle():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary dispatcher failure")
        stop_event.stopped = True

    monkeypatch.setattr(dispatcher, "run_once", flaky_cycle)

    dispatcher.run_forever(stop_event)

    assert calls == 2


def test_publish_success_message_loss_redispatches_from_postgresql(
    session_factory,
    seed_job,
) -> None:
    """broker 接受但消息丢失时 next_enqueue 到期后再次 publish。"""

    refs = seed_job()
    with session_factory() as session:
        repository = WorkflowJobRepository(session)
        first = repository.reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:first",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )[0]
        repository.finalize_dispatch_success(
            job_id=refs["job_id"],
            dispatch_owner=first.dispatch_owner,
            expected_enqueue_attempt=first.enqueue_attempt,
            redispatch_after=timedelta(milliseconds=30),
        )
        session.commit()
    time.sleep(0.06)
    with session_factory() as session:
        second = WorkflowJobRepository(session).reserve_due_jobs(
            dispatch_owner_prefix="dispatcher:redispatch",
            dispatch_lease=timedelta(seconds=15),
            batch_size=1,
        )
        session.commit()

    assert len(second) == 1
    assert second[0].workflow_job_id == refs["job_id"]
    assert second[0].enqueue_attempt == 2
