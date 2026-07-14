"""M6 Task 行锁、运行态门禁与晚期失败审计。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import TaskStatus
from cloudhelm_platform_api.services.agent_run_lifecycle import AgentRunLifecycle
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class LocalDevelopmentTaskGuard:
    """序列化推进请求，并在副作用后再次核验 Task 状态。"""

    def __init__(
        self,
        session: Session,
        lifecycle: AgentRunLifecycle,
    ) -> None:
        self.session = session
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.lifecycle = lifecycle
        self.events = EventService(session)

    def lock(self, task_id: UUID):
        """以数据库行锁读取 Task，序列化同一任务的推进请求。"""

        task = self.tasks.get(task_id, for_update=True)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        return task

    def record_finalize_failure(
        self,
        task_id: UUID,
        run_id: UUID | None,
        exc: Exception,
    ) -> None:
        """回滚晚期失败后恢复已提交的 running AgentRun 审计状态。"""

        if run_id is None:
            return
        task = self.tasks.get(task_id)
        run = self.agent_runs.get(run_id)
        if task is None or run is None or run.status != "running":
            return
        if task.status in {
            TaskStatus.PAUSED.value,
            TaskStatus.DONE.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            run.status = "failed"
            run.error_code = getattr(
                exc,
                "code",
                "local_development_finalize_failed",
            )
            run.error_message = str(exc)
            run.summary = "M6 步骤结果提交前 Task 状态已变化。"
            run.finished_at = utc_now()
            self.events.record(
                "AgentRunFailed",
                "orchestrator",
                "local-development",
                {
                    "agent_run_id": str(run.id),
                    "agent_type": run.agent_type,
                    "error_code": run.error_code,
                    "message": run.error_message,
                    "recoverable": task.status == TaskStatus.PAUSED.value,
                },
                task.id,
            )
            self.session.commit()
            return
        self.lifecycle.fail(task, run, exc)

    @staticmethod
    def ensure_can_run(task) -> None:
        """暂停、等待审批和终态 Task 不得继续产生副作用。"""

        if task.status == TaskStatus.PAUSED.value:
            raise ServiceError(
                "task_paused",
                "任务已暂停，请先恢复。",
                409,
            )
        if task.status == TaskStatus.WAITING_APPROVAL.value:
            raise ServiceError(
                "task_waiting_approval",
                "任务仍在等待审批。",
                409,
            )
        if task.status in {
            TaskStatus.DONE.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            raise ServiceError(
                "task_terminal",
                "终态任务不能继续推进 M6。",
                409,
            )
