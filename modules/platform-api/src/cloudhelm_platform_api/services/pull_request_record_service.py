"""M6 本地等价 PullRequestRecord 业务服务。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.repositories.development_plan_repository import (
    DevelopmentPlanRepository,
)
from cloudhelm_platform_api.repositories.project_repository import ProjectRepository
from cloudhelm_platform_api.repositories.pull_request_record_repository import (
    PullRequestRecordRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)
from cloudhelm_platform_api.schemas.artifact import ArtifactStatus
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.schemas.common import DevelopmentPlanStatus
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordCreate,
    PullRequestRecordRead,
    PullRequestRecordStatus,
    pull_request_record_to_read,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError

REQUIRED_ARTIFACT_TYPES = {
    "diff": {"diff_patch", "format_patch"},
    "test": {"test_report"},
    "review": {"review_report"},
    "security": {"security_report"},
}


class PullRequestRecordService(BaseService):
    """验证四类门禁证据后创建唯一 local PR record。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.records = PullRequestRecordRepository(session)
        self.tasks = TaskRepository(session)
        self.projects = ProjectRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.artifacts = ArtifactRepository(session)
        self.events = EventService(session)

    def create(
        self,
        data: PullRequestRecordCreate,
    ) -> PullRequestRecord:
        """创建或复用同一 Task/commit 的本地 PR record。"""

        existing = self.records.get_by_task_idempotency_key(
            data.task_id,
            data.idempotency_key,
        )
        if existing is not None:
            if existing.commit_sha != data.commit_sha:
                raise ServiceError(
                    "pull_request_idempotency_conflict",
                    "相同 PR record 幂等键对应不同 commit。",
                    409,
                )
            return existing
        by_commit = self.records.get_by_task_commit(
            data.task_id,
            data.commit_sha,
        )
        if by_commit is not None:
            return by_commit

        self._validate_ownership(data)
        self._validate_gate_artifacts(data)
        previous = self.records.latest_by_task(data.task_id)
        if (
            previous is not None
            and previous.status == PullRequestRecordStatus.OPEN.value
        ):
            previous.status = PullRequestRecordStatus.SUPERSEDED.value

        values = data.model_dump(mode="python")
        values["provider"] = data.provider.value
        values["status"] = data.status.value
        record = self.records.create(PullRequestRecord(**values))
        self.events.record(
            "PullRequestRecordCreated",
            "system",
            "local-development",
            {
                "pull_request_record_id": str(record.id),
                "provider": record.provider,
                "base_branch": record.base_branch,
                "head_branch": record.head_branch,
                "commit_sha": record.commit_sha,
            },
            record.task_id,
        )
        return record

    def get(self, record_id: UUID) -> PullRequestRecordRead:
        """读取单条 PR record。"""

        record = self.records.get(record_id)
        if record is None:
            raise ServiceError(
                "pull_request_record_not_found",
                "PullRequestRecord 不存在。",
                404,
            )
        return pull_request_record_to_read(record)

    def list_by_task(
        self,
        task_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> PageResponse[PullRequestRecordRead]:
        """分页读取 Task 的本地等价 PR records。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        records, next_cursor = self.records.list_by_task(
            task_id,
            limit,
            cursor,
            status=status,
        )
        return PageResponse(
            items=[pull_request_record_to_read(record) for record in records],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def _validate_ownership(self, data: PullRequestRecordCreate) -> None:
        """校验 Task、Project、Plan、AgentRun 和 ToolCall 归属。"""

        task = self.tasks.get(data.task_id)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        if task.project_id != data.project_id:
            raise ServiceError(
                "project_task_mismatch",
                "Project 不属于当前 Task。",
                409,
            )
        if self.projects.get(data.project_id) is None:
            raise ServiceError("project_not_found", "Project 不存在。", 404)
        plan = self.plans.get(data.development_plan_id)
        if plan is None:
            raise ServiceError(
                "development_plan_not_found",
                "DevelopmentPlan 不存在。",
                404,
            )
        if plan.task_id != data.task_id:
            raise ServiceError(
                "development_plan_task_mismatch",
                "DevelopmentPlan 不属于当前 Task。",
                409,
            )
        latest_plan = self.plans.latest_by_task(data.task_id)
        if (
            latest_plan is None
            or latest_plan.id != plan.id
            or plan.status != DevelopmentPlanStatus.APPROVED.value
        ):
            raise ServiceError(
                "development_plan_not_current_approved",
                "PR record 必须引用当前 Task 最新且已通过的 DevelopmentPlan。",
                409,
            )
        if data.created_by_agent_run_id is not None:
            run = self.agent_runs.get(data.created_by_agent_run_id)
            if run is None or run.task_id != data.task_id:
                raise ServiceError(
                    "agent_run_task_mismatch",
                    "创建 PR record 的 AgentRun 不属于当前 Task。",
                    409,
                )
        for tool_call_id in (
            data.branch_tool_call_id,
            data.commit_tool_call_id,
        ):
            if tool_call_id is None:
                continue
            tool_call = self.tool_calls.get(tool_call_id)
            if tool_call is None or tool_call.task_id != data.task_id:
                raise ServiceError(
                    "tool_call_task_mismatch",
                    "PR record 引用的 ToolCall 不属于当前 Task。",
                    409,
                )

    def _validate_gate_artifacts(
        self,
        data: PullRequestRecordCreate,
    ) -> None:
        """校验 diff/test/review/security Artifact 类型、归属和门禁结论。"""

        references = {
            "diff": data.diff_artifact_id,
            "test": data.test_artifact_id,
            "review": data.review_artifact_id,
            "security": data.security_artifact_id,
        }
        records = {}
        for purpose, artifact_id in references.items():
            artifact = self.artifacts.get(artifact_id)
            if artifact is None:
                raise ServiceError(
                    "artifact_not_found",
                    f"{purpose} Artifact 不存在。",
                    404,
                )
            if (
                artifact.task_id != data.task_id
                or artifact.status != ArtifactStatus.AVAILABLE.value
                or artifact.artifact_type
                not in REQUIRED_ARTIFACT_TYPES[purpose]
            ):
                raise ServiceError(
                    "pull_request_artifact_invalid",
                    f"{purpose} Artifact 类型、状态或 Task 归属无效。",
                    409,
                )
            records[purpose] = artifact

        if records["test"].metadata_json.get("passed") is not True:
            raise ServiceError(
                "test_gate_not_passed",
                "测试报告未通过，不能创建 PR record。",
                409,
            )
        if records["review"].metadata_json.get("verdict") != "approved":
            raise ServiceError(
                "review_gate_not_passed",
                "Review 结论未通过，不能创建 PR record。",
                409,
            )
        if records["security"].metadata_json.get("blocking") is not False:
            raise ServiceError(
                "security_gate_blocked",
                "Security 报告仍有阻断项。",
                409,
            )
        evidence_set_ids = {
            record.metadata_json.get("evidence_set_id")
            for record in records.values()
        }
        plan_ids = {
            record.metadata_json.get("development_plan_id")
            for record in records.values()
        }
        recipe_hashes = {
            record.metadata_json.get("recipe_sha256")
            for record in records.values()
        }
        if (
            None in evidence_set_ids
            or len(evidence_set_ids) != 1
            or plan_ids != {str(data.development_plan_id)}
            or None in recipe_hashes
            or len(recipe_hashes) != 1
        ):
            raise ServiceError(
                "pull_request_evidence_set_mismatch",
                "PR record 的 diff/test/review/security 必须来自同一 plan/recipe/rework cycle。",
                409,
            )
