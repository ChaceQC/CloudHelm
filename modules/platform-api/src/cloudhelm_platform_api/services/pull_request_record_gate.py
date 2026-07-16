"""M6 PullRequestRecord 的持久化证据门禁。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.repositories.development_plan_repository import (
    DevelopmentPlanRepository,
)
from cloudhelm_platform_api.schemas.artifact import ArtifactStatus
from cloudhelm_platform_api.schemas.common import DevelopmentPlanStatus
from cloudhelm_platform_api.services.exceptions import ServiceError

REQUIRED_ARTIFACT_TYPES = {
    "diff": {"diff_patch", "format_patch"},
    "test": {"test_report"},
    "review": {"review_report"},
    "security": {"security_report"},
}


class PullRequestRecordGate:
    """复核 PR 引用的最新计划与四类 Artifact 仍满足 M6 门禁。"""

    def __init__(self, session: Session) -> None:
        self.artifacts = ArtifactRepository(session)
        self.plans = DevelopmentPlanRepository(session)

    def validate_references(
        self,
        *,
        task_id: UUID,
        development_plan_id: UUID,
        diff_artifact_id: UUID,
        test_artifact_id: UUID,
        review_artifact_id: UUID,
        security_artifact_id: UUID,
    ) -> None:
        """校验计划身份、证据集合一致性和三类判定结论。"""

        plan = self.plans.get(development_plan_id)
        latest_plan = self.plans.latest_by_task(task_id)
        if (
            plan is None
            or plan.task_id != task_id
            or latest_plan is None
            or latest_plan.id != plan.id
            or plan.status != DevelopmentPlanStatus.APPROVED.value
        ):
            raise ServiceError(
                "development_plan_not_current_approved",
                "PR record 必须引用当前 Task 最新且已通过的 DevelopmentPlan。",
                409,
            )

        references = {
            "diff": diff_artifact_id,
            "test": test_artifact_id,
            "review": review_artifact_id,
            "security": security_artifact_id,
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
                artifact.task_id != task_id
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
            or plan_ids != {str(development_plan_id)}
            or None in recipe_hashes
            or len(recipe_hashes) != 1
        ):
            raise ServiceError(
                "pull_request_evidence_set_mismatch",
                "PR record 的 diff/test/review/security 必须来自同一 plan/recipe/rework cycle。",
                409,
            )

    def validate_record(self, record: PullRequestRecord) -> None:
        """按持久化 PR 字段重新执行门禁，供 M7 freshness 复核。"""

        self.validate_references(
            task_id=record.task_id,
            development_plan_id=record.development_plan_id,
            diff_artifact_id=record.diff_artifact_id,
            test_artifact_id=record.test_artifact_id,
            review_artifact_id=record.review_artifact_id,
            security_artifact_id=record.security_artifact_id,
        )
