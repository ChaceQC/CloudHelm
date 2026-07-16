"""M7-2D repository 查询、分页与锁入口测试。"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.service_instance import ServiceInstance
from cloudhelm_platform_api.repositories.ci_run_repository import (
    CIRunRepository,
)
from cloudhelm_platform_api.repositories.deployment_repository import (
    DeploymentRepository,
)
from cloudhelm_platform_api.repositories.service_instance_repository import (
    ServiceInstanceRepository,
)

from m7_ci_deployment_fixture import (
    build_deployment,
    build_healthy_deployment,
    build_passed_ci_run,
    build_service_instance,
    seed_m7_ci_deployment_dependencies,
)


def test_ci_run_repository_supports_all_identity_getters_and_lock() -> None:
    """CIRun repository 精确 identity getter 返回同一记录且不改状态。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        repository = CIRunRepository(session)
        ci_run = repository.create(
            build_passed_ci_run(
                references,
                external_run_id="run-42",
            )
        )
        original_status = ci_run.status

        assert repository.get(ci_run.id) is ci_run
        assert repository.get(ci_run.id, for_update=True) is ci_run
        assert (
            repository.get_by_candidate(references.release_candidate_id).id
            == ci_run.id
        )
        assert (
            repository.get_by_task_idempotency(
                references.task_id,
                ci_run.idempotency_key,
            ).id
            == ci_run.id
        )
        assert (
            repository.get_by_external_run(
                "gitea",
                ci_run.repository_external_id,
                "run-42",
                for_update=True,
            ).id
            == ci_run.id
        )
        task_items, task_cursor = repository.list_by_task(
            references.task_id,
            10,
            None,
        )
        project_items, project_cursor = repository.list_by_project(
            references.project_id,
            10,
            None,
            status="passed",
        )
        assert [item.id for item in task_items] == [ci_run.id]
        assert [item.id for item in project_items] == [ci_run.id]
        assert task_cursor is None
        assert project_cursor is None
        assert ci_run.status == original_status
        assert repository.get(uuid4()) is None


def test_deployment_repository_stable_pagination_and_identity_getters() -> None:
    """Deployment repository 使用 created_at/id 稳定排序并支持全部 identity。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        repository = DeploymentRepository(session)
        first = repository.create(
            build_deployment(
                references,
                id=uuid4(),
                ci_run_id=ci_run.id,
                release_version="0.6.0-rc.1",
                idempotency_key="deployment:first",
            )
        )
        second = repository.create(
            build_deployment(
                references,
                id=uuid4(),
                ci_run_id=ci_run.id,
                release_version="0.6.0-rc.2",
                idempotency_key="deployment:second",
            )
        )
        first.created_at = second.created_at
        first.updated_at = second.updated_at
        session.flush()

        expected = sorted(
            (first, second),
            key=lambda item: item.id,
            reverse=True,
        )
        page_one, cursor = repository.list_by_environment(
            references.environment_id,
            1,
            None,
        )
        page_two, final_cursor = repository.list_by_environment(
            references.environment_id,
            1,
            cursor,
        )
        assert [*page_one, *page_two] == expected
        assert final_cursor is None
        assert (
            repository.get_by_task_idempotency(
                references.task_id,
                first.idempotency_key,
            ).id
            == first.id
        )
        assert (
            repository.get_by_environment_release_version(
                references.environment_id,
                second.release_version,
                for_update=True,
            ).id
            == second.id
        )
        assert repository.latest_by_task(references.task_id).id == expected[0].id
        project_items, _ = repository.list_by_project(
            references.project_id,
            10,
            None,
            status="planned",
        )
        assert project_items == expected


def test_deployment_repository_reads_remote_operation_identity() -> None:
    """RemoteTarget/operation 部分唯一身份可通过锁入口读取。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        repository = DeploymentRepository(session)
        deployment = repository.create(
            build_deployment(
                references,
                ci_run_id=ci_run.id,
                status="deploying",
                approval_id=references.deployment_approval_id,
                approved_by_actor="reviewer",
                remote_operation_id="operation-42",
                started_at=references.now,
            )
        )
        selected = repository.get_by_remote_operation(
            references.remote_target_id,
            "operation-42",
            for_update=True,
        )
        assert selected is not None
        assert selected.id == deployment.id
        assert selected.status == "deploying"


def test_service_instance_repository_batch_order_page_and_lock() -> None:
    """Service repository 支持批量写入、展示排序、分页和固定锁序。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        deployment = DeploymentRepository(session).create(
            build_healthy_deployment(references, ci_run_id=ci_run.id)
        )
        repository = ServiceInstanceRepository(session)
        instances = repository.create_many(
            [
                build_service_instance(
                    references,
                    deployment_id=deployment.id,
                    service_name="worker",
                ),
                build_service_instance(
                    references,
                    deployment_id=deployment.id,
                    service_name="api",
                ),
                build_service_instance(
                    references,
                    deployment_id=deployment.id,
                    service_name="frontend",
                ),
            ]
        )
        assert [item.service_name for item in repository.list_by_deployment(
            deployment.id
        )] == ["api", "frontend", "worker"]
        locked = repository.list_by_deployment_for_update(deployment.id)
        assert [item.id for item in locked] == sorted(
            item.id for item in instances
        )
        selected = repository.get_by_deployment_service(
            deployment.id,
            "api",
            for_update=True,
        )
        assert selected is not None
        assert repository.get(selected.id).id == selected.id

        page_one, cursor = repository.list_by_environment(
            references.environment_id,
            2,
            None,
            status="starting",
        )
        page_two, final_cursor = repository.list_by_environment(
            references.environment_id,
            2,
            cursor,
            status="starting",
        )
        assert len(page_one) == 2
        assert len(page_two) == 1
        assert final_cursor is None
        assert {item.id for item in [*page_one, *page_two]} == {
            item.id for item in instances
        }


def test_service_instance_create_many_rolls_back_entire_conflicting_batch() -> None:
    """批次中一个 service 冲突时，其他新实例也不得形成半写入。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine(), expire_on_commit=False) as session:
        ci_run = CIRunRepository(session).create(
            build_passed_ci_run(references)
        )
        deployment = DeploymentRepository(session).create(
            build_healthy_deployment(references, ci_run_id=ci_run.id)
        )
        existing = build_service_instance(
            references,
            deployment_id=deployment.id,
            service_name="api",
        )
        session.add(existing)
        session.commit()
        deployment_id = deployment.id

    with Session(get_engine()) as session:
        repository = ServiceInstanceRepository(session)
        with pytest.raises(IntegrityError) as exc_info:
            repository.create_many(
                [
                    build_service_instance(
                        references,
                        deployment_id=deployment_id,
                        service_name="worker",
                    ),
                    build_service_instance(
                        references,
                        deployment_id=deployment_id,
                        service_name="api",
                    ),
                ]
            )
        assert (
            exc_info.value.orig.diag.constraint_name
            == "uq_service_instances_deployment_service"
        )
        session.rollback()

    with Session(get_engine()) as session:
        counts = dict(
            session.execute(
                select(
                    ServiceInstance.service_name,
                    func.count(),
                )
                .where(
                    ServiceInstance.deployment_id == deployment_id,
                    ServiceInstance.service_name.in_(["api", "worker"]),
                )
                .group_by(ServiceInstance.service_name)
            ).all()
        )
    assert counts == {"api": 1}


def test_repository_rejects_invalid_offset_cursor() -> None:
    """M7 repository 复用公共分页器的非法 cursor 稳定错误。"""

    references = seed_m7_ci_deployment_dependencies()
    with Session(get_engine()) as session:
        repository = CIRunRepository(session)
        with pytest.raises(ValueError, match="offset cursor"):
            repository.list_by_task(
                references.task_id,
                10,
                "not-a-number",
            )
