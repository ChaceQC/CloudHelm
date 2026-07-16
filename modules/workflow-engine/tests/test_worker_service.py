"""真实 Candidate 到 worker handler 终态的集成测试。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.services.task_service import TaskService
from cloudhelm_workflow_engine.config import WorkflowSettings
from cloudhelm_workflow_engine.handlers.release_candidate_reconcile import (
    ReleaseCandidateReconcileHandler,
)
from cloudhelm_workflow_engine.registry import (
    HandlerRegistration,
    HandlerRegistry,
)
from cloudhelm_workflow_engine.worker_service import WorkflowWorkerService
from m7_release_candidate_api_fixture import (
    seed_release_candidate_dependencies,
)


class TransientDatabaseFailureHandler:
    """模拟 handler 在真实副作用前遇到瞬时数据库错误。"""

    def execute(self, *, workflow_job_id, worker_owner):
        """抛出 SQLAlchemy OperationalError 触发 safe business retry。"""

        raise OperationalError(
            "SELECT 1",
            {},
            ConnectionError("temporary database disconnect"),
        )


def test_worker_claims_and_reconciles_real_candidate_without_run_next(
    platform_client,
    session_factory,
) -> None:
    """pending job 可由服务端 worker 自动收敛，不调用 Desktop run-next。"""

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

    worker = WorkflowWorkerService(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        registry=HandlerRegistry(
            [
                HandlerRegistration(
                    job_type="release_candidate_reconcile",
                    resource_type="release_candidate",
                    side_effect_class="none",
                    handler=ReleaseCandidateReconcileHandler(
                        session_factory
                    ),
                )
            ]
        ),
    )

    result = worker.execute(
        workflow_job_id=job_id,
        worker_owner="worker:integration-delivery-1",
    )

    assert result.outcome == "handled"
    assert result.status == "succeeded"
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(job_id)
        assert job is not None
        assert job.result_json["outcome"] == "valid"
        events = list(
            session.scalars(
                select(EventLog.event_type).where(
                    EventLog.task_id == UUID(references["task_id"])
                )
            )
        )
        assert "WorkflowJobStarted" in events
        assert "WorkflowJobSucceeded" in events


def test_duplicate_worker_delivery_is_ack_noop(
    platform_client,
    session_factory,
) -> None:
    """终态 job 的重复 Celery delivery 不重复执行 handler。"""

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
    handler = ReleaseCandidateReconcileHandler(session_factory)
    worker = WorkflowWorkerService(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        registry=HandlerRegistry(
            [
                HandlerRegistration(
                    job_type="release_candidate_reconcile",
                    resource_type="release_candidate",
                    side_effect_class="none",
                    handler=handler,
                )
            ]
        ),
    )
    first = worker.execute(
        workflow_job_id=job_id,
        worker_owner="worker:delivery-first",
    )
    second = worker.execute(
        workflow_job_id=job_id,
        worker_owner="worker:delivery-duplicate",
    )

    assert first.status == "succeeded"
    assert second.outcome == "claim_noop"
    assert second.status == "succeeded"


def test_transient_handler_error_schedules_postgresql_retry(
    session_factory,
    seed_job,
) -> None:
    """瞬时数据库异常回 pending，不调用 Celery autoretry。"""

    references = seed_job()
    worker = WorkflowWorkerService(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        registry=HandlerRegistry(
            [
                HandlerRegistration(
                    job_type="release_candidate_reconcile",
                    resource_type="release_candidate",
                    side_effect_class="none",
                    handler=TransientDatabaseFailureHandler(),
                )
            ]
        ),
    )

    result = worker.execute(
        workflow_job_id=references["job_id"],
        worker_owner="worker:transient-database",
    )

    assert result.outcome == "handler_failed"
    assert result.status == "pending"
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(references["job_id"])
        assert job is not None
        assert job.attempt == 1
        assert job.error_code == "workflow_database_transient"
        assert job.next_retry_at == job.next_enqueue_at
        event = session.scalar(
            select(EventLog).where(
                EventLog.task_id == references["task_id"],
                EventLog.event_type == "WorkflowJobRetryScheduled",
            )
        )
        assert event is not None


def test_registry_mismatch_does_not_override_concurrent_task_cancel(
    session_factory,
    seed_job,
    monkeypatch,
) -> None:
    """handler 未开始时，Task cancel 必须优先于 registry mismatch failure。"""

    references = seed_job()
    worker = WorkflowWorkerService(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        registry=HandlerRegistry([]),
    )

    def cancel_before_registry_result(_job):
        with session_factory() as session:
            TaskService(session).cancel_task(
                references["task_id"],
                "pytest-cancel",
                "取消竞态",
            )
        return None

    monkeypatch.setattr(
        worker,
        "_validated_registration",
        cancel_before_registry_result,
    )

    result = worker.execute(
        workflow_job_id=references["job_id"],
        worker_owner="worker:registry-cancel-race",
    )

    assert result.outcome == "handler_registry_invalid"
    assert result.status == "cancelled"
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(references["job_id"])
        event_types = list(
            session.scalars(
                select(EventLog.event_type).where(
                    EventLog.task_id == references["task_id"]
                )
            )
        )
        assert job is not None
        assert job.status == "cancelled"
        assert "WorkflowJobCancelRequested" in event_types
        assert "WorkflowJobCancelled" in event_types
        assert "WorkflowJobFailed" not in event_types


def test_registry_mismatch_defers_after_concurrent_task_pause(
    session_factory,
    seed_job,
    monkeypatch,
) -> None:
    """handler 未开始时，Task pause 必须撤销 attempt 而不是写 registry failure。"""

    references = seed_job()
    worker = WorkflowWorkerService(
        settings=WorkflowSettings(),
        session_factory=session_factory,
        registry=HandlerRegistry([]),
    )

    def pause_before_registry_result(_job):
        with session_factory() as session:
            TaskService(session).pause_task(
                references["task_id"],
                "pytest-pause",
                "暂停竞态",
            )
        return None

    monkeypatch.setattr(
        worker,
        "_validated_registration",
        pause_before_registry_result,
    )

    result = worker.execute(
        workflow_job_id=references["job_id"],
        worker_owner="worker:registry-pause-race",
    )

    assert result.outcome == "handler_registry_invalid"
    assert result.status == "pending"
    with session_factory() as session:
        job = WorkflowJobRepository(session).get(references["job_id"])
        event_types = list(
            session.scalars(
                select(EventLog.event_type).where(
                    EventLog.task_id == references["task_id"]
                )
            )
        )
        assert job is not None
        assert job.status == "pending"
        assert job.attempt == 0
        assert job.error_code == "workflow_job_task_paused"
        assert "WorkflowJobExecutionDeferred" in event_types
        assert "WorkflowJobFailed" not in event_types
