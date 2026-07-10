"""Task 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.project_repository import ProjectRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import ToolCallRepository
from cloudhelm_platform_api.schemas.common import (
    AgentRunStatus,
    ApprovalStatus,
    PageInfo,
    PageResponse,
    TaskStatus,
    ToolCallStatus,
)
from cloudhelm_platform_api.schemas.task import TaskCreate, TaskRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class TaskService(BaseService):
    """Task 用例服务，负责状态流转和事件写入。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.projects = ProjectRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.approvals = ApprovalRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.events = EventService(session)

    def create_task(self, data: TaskCreate) -> TaskRead:
        """创建任务，初始状态为 `created` / `Created`。"""

        if self.projects.get(data.project_id) is None:
            raise ServiceError("project_not_found", "创建任务失败：项目不存在。", 404)
        task = self.tasks.create(
            Task(
                **data.model_dump(mode="json"),
                status=TaskStatus.CREATED.value,
                current_phase="Created",
            )
        )
        self.events.record(
            event_type="TaskCreated",
            actor_type="user",
            actor_id=data.created_by,
            task_id=task.id,
            payload={"task_id": str(task.id), "project_id": str(task.project_id), "status": task.status},
        )
        self.commit()
        return TaskRead.model_validate(task)

    def get_task(self, task_id: UUID) -> TaskRead:
        """读取任务。"""

        return TaskRead.model_validate(self._require_task(task_id))

    def list_tasks(
        self,
        limit: int,
        cursor: str | None,
        project_id: UUID | None = None,
    ) -> PageResponse[TaskRead]:
        """分页读取任务。"""

        items, next_cursor = self.tasks.list(limit, cursor, project_id)
        return PageResponse(
            items=[TaskRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def pause_task(self, task_id: UUID, actor_id: str, reason: str | None = None) -> TaskRead:
        """暂停任务并写入事件，同时保留可恢复的业务阶段。"""

        task = self._require_task(task_id)
        if task.status not in {
            TaskStatus.CREATED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.WAITING_APPROVAL.value,
        }:
            raise ServiceError("invalid_task_transition", "当前任务状态不允许暂停。", 409)
        old_status = task.status
        task.status = TaskStatus.PAUSED.value
        self.events.record(
            "TaskPaused",
            "user",
            actor_id,
            {"task_id": str(task.id), "from_status": old_status, "reason": reason},
            task.id,
        )
        self.commit()
        return TaskRead.model_validate(task)

    def resume_task(self, task_id: UUID, actor_id: str, reason: str | None = None) -> TaskRead:
        """恢复暂停任务并从暂停前业务阶段继续调度。"""

        task = self._require_task(task_id)
        if task.status != TaskStatus.PAUSED.value:
            raise ServiceError("invalid_task_transition", "只有 paused 任务可以恢复。", 409)
        pause_event = self.events.latest(task.id, "TaskPaused")
        previous_status = pause_event.payload.get("from_status") if pause_event is not None else None
        if previous_status not in {
            TaskStatus.CREATED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.WAITING_APPROVAL.value,
        }:
            raise ServiceError("resume_state_missing", "缺少可恢复的暂停前状态。", 409)
        if previous_status == TaskStatus.WAITING_APPROVAL.value and not self.approvals.has_pending_by_task(task.id):
            previous_status = TaskStatus.RUNNING.value
        task.status = previous_status
        self.events.record(
            "TaskResumed",
            "user",
            actor_id,
            {"task_id": str(task.id), "to_status": task.status, "current_phase": task.current_phase, "reason": reason},
            task.id,
        )
        self.commit()
        return TaskRead.model_validate(task)

    def cancel_task(self, task_id: UUID, actor_id: str, reason: str | None = None) -> TaskRead:
        """取消任务并写入 TaskCancelled 事件。"""

        task = self._require_task(task_id)
        if task.status in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
            raise ServiceError("invalid_task_transition", "当前任务状态不允许取消。", 409)
        old_status = task.status
        task.status = TaskStatus.CANCELLED.value
        task.current_phase = "Cancelled"
        cancelled_runs = self._cancel_agent_runs(task, actor_id, reason)
        cancelled_calls = self._cancel_tool_calls(task, actor_id, reason)
        expired_approvals = self._expire_approvals(task, actor_id, reason)
        self.events.record(
            "TaskCancelled",
            "user",
            actor_id,
            {
                "task_id": str(task.id),
                "from_status": old_status,
                "reason": reason,
                "cancelled_agent_runs": cancelled_runs,
                "cancelled_tool_calls": cancelled_calls,
                "expired_approvals": expired_approvals,
            },
            task.id,
        )
        self.commit()
        return TaskRead.model_validate(task)

    def _require_task(self, task_id: UUID) -> Task:
        """读取任务或抛出稳定 404。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        return task

    def _cancel_agent_runs(self, task: Task, actor_id: str, reason: str | None) -> int:
        """取消任务中尚未结束的 AgentRun，并逐项写入事件。"""

        runs = self.agent_runs.list_active_by_task(task.id)
        for agent_run in runs:
            agent_run.status = AgentRunStatus.CANCELLED.value
            agent_run.summary = "任务已取消，AgentRun 终止。"
            agent_run.error_code = "task_cancelled"
            agent_run.error_message = reason or "任务被用户取消。"
            agent_run.finished_at = utc_now()
            self.events.record(
                "AgentRunCancelled",
                "user",
                actor_id,
                {"agent_run_id": str(agent_run.id), "agent_type": agent_run.agent_type, "reason": reason},
                task.id,
            )
        return len(runs)

    def _cancel_tool_calls(self, task: Task, actor_id: str, reason: str | None) -> int:
        """取消任务中尚未结束或仍等待审批的 ToolCall。"""

        calls = self.tool_calls.list_active_by_task(task.id)
        for tool_call in calls:
            tool_call.status = ToolCallStatus.CANCELLED.value
            tool_call.error_code = "task_cancelled"
            tool_call.result_summary = "任务已取消，ToolCall 不再继续。"
            tool_call.finished_at = utc_now()
            tool_call.audit_json = {**tool_call.audit_json, "status": ToolCallStatus.CANCELLED.value}
            self.events.record(
                "ToolCallCancelled",
                "user",
                actor_id,
                {"tool_call_id": str(tool_call.id), "tool_name": tool_call.tool_name, "reason": reason},
                task.id,
            )
        return len(calls)

    def _expire_approvals(self, task: Task, actor_id: str, reason: str | None) -> int:
        """把任务剩余待审批记录标记为过期。"""

        approvals = self.approvals.list_pending_by_task(task.id)
        for approval in approvals:
            approval.status = ApprovalStatus.EXPIRED.value
            approval.decided_by = actor_id
            approval.decided_at = utc_now()
            self.events.record(
                "ApprovalExpired",
                "user",
                actor_id,
                {"approval_id": str(approval.id), "action": approval.action, "reason": reason or "任务已取消。"},
                task.id,
            )
        return len(approvals)
