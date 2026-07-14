"""M6 最新审批上下文与 execution recipe 解析。"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import (
    DevelopmentPlanRepository,
)
from cloudhelm_platform_api.repositories.project_repository import ProjectRepository
from cloudhelm_platform_api.repositories.requirement_repository import (
    RequirementRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import (
    DevelopmentPlanStatus,
    ReviewStatus,
)
from cloudhelm_platform_api.schemas.local_execution_recipe import (
    LocalExecutionRecipe,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_workspace_resolver import (
    LocalWorkspaceResolver,
)


@dataclass(frozen=True, slots=True)
class LocalDevelopmentContext:
    """一次 M6 请求使用的最新版、已审批输入快照。"""

    task: Task
    project: Project
    requirement: RequirementSpec
    design: TechnicalDesign
    plan: DevelopmentPlan
    recipe: LocalExecutionRecipe
    recipe_sha256: str


class LocalDevelopmentContextResolver:
    """校验 fixture 项目、最新版审批链和受控 recipe。"""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.tasks = TaskRepository(session)
        self.projects = ProjectRepository(session)
        self.requirements = RequirementRepository(session)
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.workspace = LocalWorkspaceResolver(settings)

    def resolve(self, task_id: UUID) -> LocalDevelopmentContext:
        """读取 M6 上下文；任一 stale/未审批/非 fixture 条件均拒绝。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        project = self.projects.get(task.project_id)
        if project is None:
            raise ServiceError("project_not_found", "任务所属 Project 不存在。", 404)
        if (
            project.provider != "local"
            or project.repo_url != "fixture://sample-repo-python"
        ):
            raise ServiceError(
                "m6_project_not_local_fixture",
                "M6 只允许已登记的 local sample-repo-python fixture。",
                409,
            )

        requirement = self.requirements.latest_by_task(task.id)
        design = self.designs.latest_by_task(task.id)
        plan = self.plans.latest_by_task(task.id)
        if requirement is None or requirement.status != ReviewStatus.APPROVED.value:
            raise ServiceError(
                "approved_requirement_missing",
                "M6 需要当前最新版已通过 RequirementSpec。",
                409,
            )
        if (
            design is None
            or design.requirement_spec_id != requirement.id
            or design.status != ReviewStatus.APPROVED.value
        ):
            raise ServiceError(
                "approved_technical_design_missing",
                "M6 需要对应当前需求的最新版已通过 TechnicalDesign。",
                409,
            )
        if (
            plan is None
            or plan.technical_design_id != design.id
            or plan.status != DevelopmentPlanStatus.APPROVED.value
        ):
            raise ServiceError(
                "approved_development_plan_missing",
                "M6 需要对应当前设计的最新版已通过 DevelopmentPlan。",
                409,
            )

        recipe_id = self._recipe_id(plan)
        recipe, recipe_sha256 = self._load_recipe(recipe_id)
        plan_step_ids = {
            str(step.get("id"))
            for step in plan.steps_json
            if isinstance(step, dict) and step.get("id")
        }
        if not set(recipe.step_ids).issubset(plan_step_ids):
            raise ServiceError(
                "m6_recipe_plan_mismatch",
                "Execution recipe 引用的步骤不属于当前 DevelopmentPlan。",
                409,
            )
        if task.source_ref != recipe.issue_path:
            raise ServiceError(
                "m6_recipe_issue_mismatch",
                "Execution recipe 与 Task source_ref 不一致。",
                409,
            )
        requirement_ids = {
            str(item.get("id"))
            for item in requirement.acceptance_criteria_json
            if isinstance(item, dict) and item.get("id")
        }
        recipe_ids = {
            item.criterion_id for item in recipe.acceptance_evidence
        }
        if not requirement_ids or recipe_ids != requirement_ids:
            raise ServiceError(
                "m6_recipe_acceptance_mismatch",
                "Execution recipe 的 AC 集合必须与当前 RequirementSpec 精确一致。",
                409,
            )
        return LocalDevelopmentContext(
            task=task,
            project=project,
            requirement=requirement,
            design=design,
            plan=plan,
            recipe=recipe,
            recipe_sha256=recipe_sha256,
        )

    @staticmethod
    def _recipe_id(plan: DevelopmentPlan) -> str:
        """从计划步骤中读取唯一 execution_recipe。"""

        recipe_ids = {
            str(step["execution_recipe"])
            for step in plan.steps_json
            if isinstance(step, dict) and step.get("execution_recipe")
        }
        if len(recipe_ids) != 1:
            raise ServiceError(
                "m6_execution_recipe_missing",
                "当前 DevelopmentPlan 必须引用唯一 execution_recipe。",
                409,
            )
        return next(iter(recipe_ids))

    def _load_recipe(
        self,
        recipe_id: str,
    ) -> tuple[LocalExecutionRecipe, str]:
        """以 UTF-8 读取并严格校验受控 recipe JSON。"""

        path = self.workspace.recipe_file(recipe_id)
        try:
            content = path.read_bytes()
            payload = json.loads(content.decode("utf-8"))
            recipe = LocalExecutionRecipe.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ServiceError(
                "m6_recipe_invalid",
                f"Execution recipe 校验失败：{type(exc).__name__}。",
                409,
            ) from exc
        if recipe.recipe_id != recipe_id:
            raise ServiceError(
                "m6_recipe_identity_mismatch",
                "Execution recipe 文件身份与 DevelopmentPlan 引用不一致。",
                409,
            )
        return recipe, f"sha256:{hashlib.sha256(content).hexdigest()}"
