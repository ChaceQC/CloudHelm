"""M6 状态、下一动作和最新证据的只读聚合。"""

from uuid import UUID

from cloudhelm_orchestrator.local_development_state_machine import (
    LocalDevelopmentStateMachine,
    LocalDevelopmentStateMachineError,
)
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.repositories.pull_request_record_repository import (
    PullRequestRecordRepository,
)
from cloudhelm_platform_api.schemas.local_development import (
    LocalDevelopmentStateRead,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContextResolver,
)


class LocalDevelopmentStateReader:
    """读取当前阶段、active run、Artifact 和 PR record 引用。"""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        machine: LocalDevelopmentStateMachine,
    ) -> None:
        self.contexts = LocalDevelopmentContextResolver(session, settings)
        self.agent_runs = AgentRunRepository(session)
        self.artifacts = ArtifactRepository(session)
        self.pr_records = PullRequestRecordRepository(session)
        self.machine = machine

    def get(self, task_id: UUID) -> LocalDevelopmentStateRead:
        """返回控制台推进按钮和 evidence 刷新需要的状态摘要。"""

        context = self.contexts.resolve(task_id)
        try:
            next_action = self.machine.next_action(
                context.task.current_phase
            )
        except LocalDevelopmentStateMachineError as exc:
            raise ServiceError(
                "local_development_phase_out_of_scope",
                str(exc),
                409,
            ) from exc
        active = self.agent_runs.list_active_by_task(task_id)
        latest_artifact_ids = {}
        for artifact_type in (
            "workspace_manifest",
            "diff_patch",
            "junit_xml",
            "test_report",
            "review_report",
            "security_report",
            "format_patch",
        ):
            artifact = (
                self.artifacts.latest_by_task_type_and_execution_context(
                    task_id,
                    artifact_type,
                    development_plan_id=context.plan.id,
                    recipe_sha256=context.recipe_sha256,
                    status="available",
                )
            )
            if artifact is not None:
                latest_artifact_ids[artifact_type] = artifact.id
        latest_pr = self.pr_records.latest_by_task_and_plan(
            task_id,
            context.plan.id,
            context.recipe_sha256,
        )
        return LocalDevelopmentStateRead(
            task_id=task_id,
            current_phase=context.task.current_phase,
            next_action=next_action.value,
            development_plan_id=context.plan.id,
            active_agent_run_id=active[0].id if active else None,
            latest_artifact_ids=latest_artifact_ids,
            latest_pull_request_record_id=(
                latest_pr.id if latest_pr is not None else None
            ),
        )
