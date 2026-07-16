"""WSL Redis restart、PostgreSQL 补投与真实 Celery worker E2E。"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from redis import Redis

from cloudhelm_platform_api.repositories.project_repository_binding_repository import (
    ProjectRepositoryBindingRepository,
)
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_workflow_engine.broker import CeleryBrokerPublisher
from cloudhelm_workflow_engine.celery_app import create_celery_app
from cloudhelm_workflow_engine.config import (
    WorkflowSettings,
    get_workflow_settings,
)
from cloudhelm_workflow_engine.dispatcher import WorkflowDispatcher
from cloudhelm_workflow_engine.stale_reclaimer import StaleReclaimer
from m7_release_candidate_api_fixture import (
    seed_release_candidate_dependencies,
)

WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
ISOLATED_REDIS_CONTAINER = "cloudhelm-redis-workflow-test"
ISOLATED_REDIS_URL = "redis://127.0.0.1:16380/15"
ISOLATED_REDIS_IMAGE = "redis:7-alpine"


@pytest.fixture()
def isolated_redis_container():
    """创建并最终删除固定端口/DB 的隔离 Redis，禁止误清共享 broker。"""

    container = os.environ.get(
        "CLOUDHELM_WORKFLOW_TEST_REDIS_CONTAINER",
        ISOLATED_REDIS_CONTAINER,
    )
    broker_url = os.environ.get(
        "CLOUDHELM_WORKFLOW_BROKER_URL",
        ISOLATED_REDIS_URL,
    )
    _validate_isolated_redis(container, broker_url)
    previous_url = os.environ.get("CLOUDHELM_WORKFLOW_BROKER_URL")
    os.environ["CLOUDHELM_WORKFLOW_BROKER_URL"] = broker_url
    get_workflow_settings.cache_clear()
    _remove_container(container)
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            container,
            "--restart",
            "no",
            "--publish",
            "127.0.0.1:16380:6379",
            ISOLATED_REDIS_IMAGE,
            "redis-server",
            "--appendonly",
            "no",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    client = Redis.from_url(broker_url, decode_responses=True)
    _wait_for_redis(client)
    try:
        yield container, client
    finally:
        _remove_container(container)
        if previous_url is None:
            os.environ.pop("CLOUDHELM_WORKFLOW_BROKER_URL", None)
        else:
            os.environ["CLOUDHELM_WORKFLOW_BROKER_URL"] = previous_url
        get_workflow_settings.cache_clear()


@pytest.mark.workflow_integration
@pytest.mark.skipif(
    os.environ.get("CLOUDHELM_RUN_WORKFLOW_INTEGRATION") != "1",
    reason="需要显式启用 WSL Celery/Redis restart 集成测试。",
)
def test_redis_restart_requeues_postgresql_pending_job(
    platform_client,
    session_factory,
    isolated_redis_container,
) -> None:
    """Redis 故障期间 job 保持 pending，恢复后由 dispatcher 补投并成功执行。"""

    container, redis_client = isolated_redis_container
    settings = WorkflowSettings()
    redis_client.flushdb()
    _docker("stop", container)

    references = seed_release_candidate_dependencies(platform_client)
    response = platform_client.post(
        f"/api/tasks/{references['task_id']}/release-candidate",
        json={},
    )
    assert response.status_code == 201, response.text
    candidate_id = UUID(response.json()["candidate"]["id"])
    with session_factory() as session:
        job = WorkflowJobRepository(session).get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_id,
        )
        assert job is not None
        job_id = job.id

    dispatcher = WorkflowDispatcher(
        settings=settings,
        session_factory=session_factory,
        publisher=CeleryBrokerPublisher(
            app=create_celery_app(settings),
            settings=settings,
        ),
    )
    failed_cycle = dispatcher.run_once()
    assert failed_cycle.deferred == 1
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(job_id)
        assert job is not None
        assert job.status == "pending"
        assert job.last_enqueue_error_code is not None

    _docker("start", container)
    _wait_for_redis(redis_client)
    worker = _start_worker(settings)
    try:
        time.sleep(settings.enqueue_backoff_seconds + 0.5)
        recovered_cycle = dispatcher.run_once()
        assert recovered_cycle.published == 1
        status = _wait_for_job_status(
            session_factory,
            job_id,
            expected="succeeded",
            timeout=30,
        )
        assert status == "succeeded"
        with session_factory() as session:
            job = WorkflowJobRepository(session).get(job_id)
            assert job is not None
            assert job.attempt == 1
            assert job.result_json["outcome"] == "valid"
    finally:
        _stop_worker(worker)


@pytest.mark.workflow_integration
@pytest.mark.skipif(
    os.environ.get("CLOUDHELM_RUN_WORKFLOW_INTEGRATION") != "1",
    reason="需要显式启用 WSL prefork hard-crash 集成测试。",
)
def test_prefork_hard_crash_reclaims_running_none_job(
    platform_client,
    session_factory,
    isolated_redis_container,
    monkeypatch,
) -> None:
    """真实 prefork 进程组 SIGKILL 后由 PostgreSQL lease 安全回排。"""

    _container, redis_client = isolated_redis_container
    redis_client.flushdb()
    monkeypatch.setenv("CLOUDHELM_WORKFLOW_JOB_LEASE_SECONDS", "3")
    monkeypatch.setenv(
        "CLOUDHELM_WORKFLOW_JOB_HEARTBEAT_SECONDS",
        "1",
    )
    monkeypatch.setenv("CLOUDHELM_WORKFLOW_RECLAIM_INTERVAL_SECONDS", "1")
    get_workflow_settings.cache_clear()
    settings = WorkflowSettings()
    references = seed_release_candidate_dependencies(platform_client)
    response = platform_client.post(
        f"/api/tasks/{references['task_id']}/release-candidate",
        json={},
    )
    assert response.status_code == 201, response.text
    candidate_id = UUID(response.json()["candidate"]["id"])
    with session_factory() as session:
        job = WorkflowJobRepository(session).get_by_resource(
            job_type="release_candidate_reconcile",
            resource_type="release_candidate",
            resource_id=candidate_id,
        )
        assert job is not None
        job_id = job.id

    blocker = session_factory()
    binding = ProjectRepositoryBindingRepository(blocker).get(
        UUID(references["repository_binding_id"]),
        for_update=True,
    )
    assert binding is not None
    dispatcher = WorkflowDispatcher(
        settings=settings,
        session_factory=session_factory,
        publisher=CeleryBrokerPublisher(
            app=create_celery_app(settings),
            settings=settings,
        ),
    )
    worker = _start_worker(settings)
    try:
        time.sleep(1.5)
        cycle = dispatcher.run_once()
        assert cycle.published == 1
        assert (
            _wait_for_job_status(
                session_factory,
                job_id,
                expected="running",
                timeout=20,
            )
            == "running"
        )
        _kill_worker_hard(worker)
        blocker.commit()
        time.sleep(settings.job_lease_seconds + 0.5)
        reclaimed = StaleReclaimer(
            settings=settings,
            session_factory=session_factory,
        ).run_once()
        assert reclaimed.reclaimed == 1
        with session_factory() as session:
            job = WorkflowJobRepository(session).get(job_id)
            assert job is not None
            assert job.status == "pending"
            assert job.error_code == "workflow_job_worker_lease_expired"
            assert job.next_retry_at == job.next_enqueue_at
    finally:
        if worker.poll() is None:
            _kill_worker_hard(worker)
        blocker.rollback()
        blocker.close()
        get_workflow_settings.cache_clear()


def _docker(action: str, container: str) -> None:
    """启动或停止隔离 Redis container。"""

    result = subprocess.run(
        ["docker", action, container],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"docker {action} {container} 失败：{result.stderr.strip()}"
        )


def _remove_container(container: str) -> None:
    """幂等删除固定测试 container，不触碰共享 Redis。"""

    subprocess.run(
        ["docker", "rm", "--force", container],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def _validate_isolated_redis(container: str, broker_url: str) -> None:
    """强制 integration 使用 16380/15 与固定测试 container。"""

    parsed = urlparse(broker_url)
    if (
        container != ISOLATED_REDIS_CONTAINER
        or parsed.scheme != "redis"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 16380
        or parsed.path != "/15"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError(
            "Workflow integration 必须使用 "
            f"{ISOLATED_REDIS_CONTAINER} 与 {ISOLATED_REDIS_URL}。"
        )


def _wait_for_redis(client: Redis) -> None:
    """等待隔离 Redis 恢复 PONG。"""

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if client.ping():
                return
        except Exception:
            time.sleep(0.2)
    raise AssertionError("隔离 Redis 未在 20 秒内恢复。")


def _start_worker(settings: WorkflowSettings) -> subprocess.Popen:
    """在当前 WSL Python 环境启动真实 prefork Celery worker。"""

    hostname = f"workflow-test-{uuid4().hex[:8]}@%h"
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "cloudhelm_workflow_engine.celery_app:celery_app",
            "worker",
            "--queues",
            settings.queue_name,
            "--pool",
            "prefork",
            "--concurrency",
            "1",
            "--hostname",
            hostname,
            "--loglevel",
            "WARNING",
            "--without-gossip",
            "--without-mingle",
        ],
        cwd=WORKFLOW_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
        start_new_session=True,
    )


def _wait_for_job_status(
    session_factory,
    job_id: UUID,
    *,
    expected: str,
    timeout: int,
) -> str | None:
    """轮询 PostgreSQL 权威状态，不读取 Celery result backend。"""

    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        with session_factory() as session:
            job = WorkflowJobRepository(session).get(job_id)
            status = job.status if job is not None else None
        if status == expected:
            return status
        time.sleep(0.2)
    return status


def _stop_worker(worker: subprocess.Popen) -> None:
    """向独立进程组发送 SIGTERM，并在超时后强制清理。"""

    if worker.poll() is not None:
        return
    os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _kill_worker_hard(worker)


def _kill_worker_hard(worker: subprocess.Popen) -> None:
    """SIGKILL 整个 prefork 进程组，避免遗留 orphan child。"""

    if worker.poll() is not None:
        return
    os.killpg(os.getpgid(worker.pid), signal.SIGKILL)
    worker.wait(timeout=5)
