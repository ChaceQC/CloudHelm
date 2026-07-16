"""M7-2D 唯一身份的真实 PostgreSQL 并发竞争测试。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event, Thread
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.ci_run import CIRun
from cloudhelm_platform_api.models.deployment import Deployment
from cloudhelm_platform_api.models.service_instance import ServiceInstance
from cloudhelm_platform_api.repositories.ci_run_repository import (
    CIRunRepository,
)
from cloudhelm_platform_api.repositories.deployment_repository import (
    DeploymentRepository,
)

from m7_ci_deployment_fixture import (
    build_ci_run,
    build_deployment,
    build_healthy_deployment,
    build_passed_ci_run,
    build_service_instance,
    seed_m7_ci_deployment_dependencies,
)


def _race(
    build_value: Callable[[int], Any],
    expected_constraint: str,
) -> list[str]:
    """让两个独立 Session 同时提交，并返回成功或精确约束名。"""

    barrier = Barrier(2)

    def attempt(index: int) -> str:
        with Session(get_engine()) as session:
            value = build_value(index)
            session.add(value)
            barrier.wait(timeout=10)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                return str(exc.orig.diag.constraint_name)
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, (0, 1)))
    assert sorted(outcomes) == sorted(["committed", expected_constraint])
    return outcomes


def test_same_candidate_ci_run_concurrency_commits_once() -> None:
    """同一 Candidate 并发创建 CIRun 时仅一条成功。"""

    references = seed_m7_ci_deployment_dependencies()

    _race(
        lambda index: build_ci_run(
            references,
            id=uuid4(),
            idempotency_key=f"ci-race:{index}",
        ),
        "uq_ci_runs_release_candidate",
    )
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(CIRun)
            .where(
                CIRun.release_candidate_id
                == references.release_candidate_id
            )
        )
    assert count == 1


def test_same_task_deployment_idempotency_concurrency_commits_once() -> None:
    """同 Task/idempotency key 并发创建 Deployment 时仅一条成功。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        session.commit()
        ci_run_id = ci_run.id

    _race(
        lambda index: build_deployment(
            references,
            id=uuid4(),
            ci_run_id=ci_run_id,
            release_version=f"0.6.0-race-{index}",
            idempotency_key="deployment:shared-idempotency",
        ),
        "uq_deployments_task_idempotency",
    )
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(Deployment)
            .where(
                Deployment.task_id == references.task_id,
                Deployment.idempotency_key
                == "deployment:shared-idempotency",
            )
        )
    assert count == 1


def test_same_environment_release_version_concurrency_commits_once() -> None:
    """同 Environment/release version 并发创建时仅一条成功。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        session.commit()
        ci_run_id = ci_run.id

    _race(
        lambda index: build_deployment(
            references,
            id=uuid4(),
            ci_run_id=ci_run_id,
            release_version="0.6.0-shared",
            idempotency_key=f"deployment:environment-race:{index}",
        ),
        "uq_deployments_environment_release_version",
    )
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(Deployment)
            .where(
                Deployment.environment_id == references.environment_id,
                Deployment.release_version == "0.6.0-shared",
            )
        )
    assert count == 1


def test_same_deployment_service_concurrency_commits_once() -> None:
    """同 Deployment/service 并发创建 ServiceInstance 时仅一条成功。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        deployment = DeploymentRepository(session).create(
            build_healthy_deployment(references, ci_run_id=ci_run.id)
        )
        session.commit()
        deployment_id = deployment.id

    _race(
        lambda index: build_service_instance(
            references,
            id=uuid4(),
            deployment_id=deployment_id,
            service_name="shared-api",
            runtime_ref=f"container-{index}",
        ),
        "uq_service_instances_deployment_service",
    )
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(ServiceInstance)
            .where(
                ServiceInstance.deployment_id == deployment_id,
                ServiceInstance.service_name == "shared-api",
            )
        )
    assert count == 1


def test_provider_repository_run_partial_unique_index_commits_once() -> None:
    """跨 Task 的同 provider/repository/run identity 只能落一条 CIRun。"""

    references = [
        seed_m7_ci_deployment_dependencies(),
        seed_m7_ci_deployment_dependencies(),
    ]
    _race(
        lambda index: build_passed_ci_run(
            references[index],
            id=uuid4(),
            external_run_id="shared-provider-run",
            idempotency_key=f"ci:provider-run:{index}",
        ),
        "ux_ci_runs_provider_repository_run",
    )


def test_deployment_approval_partial_unique_index_commits_once() -> None:
    """同一 L3 Approval 不能被两个 Deployment 消费。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        session.commit()
        ci_run_id = ci_run.id

    _race(
        lambda index: build_deployment(
            references,
            id=uuid4(),
            ci_run_id=ci_run_id,
            approval_id=references.deployment_approval_id,
            status="pending_approval",
            release_version=f"0.6.0-approval-race-{index}",
            idempotency_key=f"deployment:approval-race:{index}",
        ),
        "ux_deployments_approval",
    )


def test_remote_operation_partial_unique_index_commits_once() -> None:
    """同一 RemoteTarget/operation identity 只能绑定一个 Deployment。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        session.commit()
        ci_run_id = ci_run.id

    deployment_ids = [
        references.deployment_id,
        references.historical_deployment_id,
    ]
    approval_ids = [
        references.deployment_approval_id,
        references.historical_deployment_approval_id,
    ]
    _race(
        lambda index: build_deployment(
            references,
            id=deployment_ids[index],
            ci_run_id=ci_run_id,
            approval_id=approval_ids[index],
            approved_by_actor="reviewer",
            remote_operation_id="shared-remote-operation",
            status="deploying",
            started_at=references.now,
            release_version=f"0.6.0-operation-race-{index}",
            idempotency_key=f"deployment:operation-race:{index}",
        ),
        "ux_deployments_remote_target_operation",
    )


def test_for_update_blocks_second_session_until_holder_commits() -> None:
    """两个真实 Session 必须竞争同一 CIRun 行锁，而非只检查 SQL 形态。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        session.commit()
        ci_run_id = ci_run.id

    contender_pid: Queue[int] = Queue(maxsize=1)
    contender_error: Queue[BaseException] = Queue(maxsize=1)
    acquired = Event()

    def contend() -> None:
        try:
            with Session(get_engine()) as session:
                session.execute(
                    text("SET LOCAL statement_timeout = '5s'")
                )
                pid = session.scalar(select(func.pg_backend_pid()))
                assert pid is not None
                contender_pid.put(pid)
                locked = CIRunRepository(session).get(
                    ci_run_id,
                    for_update=True,
                )
                assert locked is not None
                acquired.set()
                session.rollback()
        except BaseException as error:  # pragma: no cover - 线程回传
            contender_error.put(error)

    with Session(get_engine()) as holder:
        locked = CIRunRepository(holder).get(ci_run_id, for_update=True)
        assert locked is not None
        thread = Thread(target=contend, daemon=True)
        thread.start()
        pid = contender_pid.get(timeout=5)
        assert _wait_until_row_lock(pid)
        assert not acquired.is_set()
        holder.commit()

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert contender_error.empty(), list(contender_error.queue)
    assert acquired.is_set()


def _wait_until_row_lock(pid: int) -> bool:
    """轮询 pg_stat_activity，确定第二个 backend 已进入 Lock wait。"""

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with get_engine().connect() as connection:
            waiting = connection.scalar(
                text(
                    """
                    SELECT wait_event_type = 'Lock'
                    FROM pg_stat_activity
                    WHERE pid = :pid
                    """
                ),
                {"pid": pid},
            )
        if waiting:
            return True
        time.sleep(0.02)
    return False
