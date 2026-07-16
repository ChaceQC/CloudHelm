"""Celery task delivery identity 门禁。"""

from uuid import uuid4

from cloudhelm_workflow_engine import tasks


class RecordingWorkerService:
    """记录 task 入口生成的 worker owner。"""

    def __init__(self) -> None:
        self.owners: list[str] = []

    def execute(self, *, workflow_job_id, worker_owner):
        """保存 owner；本测试不访问数据库。"""

        self.owners.append(worker_owner)


def test_same_celery_task_id_uses_unique_claim_owner(monkeypatch) -> None:
    """同一 task id 的 redelivery 也必须获得新的 claim token。"""

    service = RecordingWorkerService()
    monkeypatch.setattr(tasks, "get_worker_service", lambda: service)
    message = {"workflow_job_id": str(uuid4())}

    for _ in range(2):
        tasks.execute_workflow_job.push_request(id="same-celery-task-id")
        try:
            tasks.execute_workflow_job.run(**message)
        finally:
            tasks.execute_workflow_job.pop_request()

    assert len(service.owners) == 2
    assert service.owners[0] != service.owners[1]
    assert all(
        ":same-celery-task-id:" in owner for owner in service.owners
    )
