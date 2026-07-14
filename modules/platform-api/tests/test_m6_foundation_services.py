"""M6 Artifact 生产者与本地 PR 门禁服务白盒测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.pull_request_record_service import (
    PullRequestRecordService,
)
from m6_service_fixtures import pr_payload, project_and_task


def test_pull_request_record_requires_latest_approved_plan() -> None:
    """旧计划或未审批最新版均不能成为本地 PR record 基线。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        project, task = project_and_task(session, "pr-plan-gate")
        requirement = RequirementSpec(
            task_id=task.id,
            project_id=project.id,
            source_type="manual",
            raw_input="验证 PR plan gate。",
            constraints_json=[],
            acceptance_criteria_json=[],
            status="approved",
            version=1,
        )
        session.add(requirement)
        session.flush()
        design = TechnicalDesign(
            task_id=task.id,
            requirement_spec_id=requirement.id,
            design_type="m6-test",
            content_markdown="# M6",
            risk_level="L1",
            status="approved",
            version=1,
        )
        session.add(design)
        session.flush()
        old_plan = DevelopmentPlan(
            task_id=task.id,
            project_id=project.id,
            technical_design_id=design.id,
            summary="旧计划",
            steps_json=[{"id": "STEP-001"}],
            risks_json=[],
            status="approved",
            version=1,
        )
        session.add(old_plan)
        session.commit()

        latest_plan = DevelopmentPlan(
            task_id=task.id,
            project_id=project.id,
            technical_design_id=design.id,
            summary="待审批最新版计划",
            steps_json=[{"id": "STEP-001"}],
            risks_json=[],
            status="ready_for_review",
            version=2,
        )
        session.add(latest_plan)
        session.commit()

        artifacts = ArtifactService(session)
        evidence_metadata = {
            "evidence_set_id": "pr-gate:cycle:1",
            "development_plan_id": str(latest_plan.id),
            "recipe_sha256": "sha256:" + ("a" * 64),
        }
        evidence = {
            "diff": artifacts.create_text(
                task_id=task.id,
                artifact_type="diff_patch",
                display_name="changes.patch",
                content="diff",
                producer_type=ArtifactProducerType.SYSTEM,
                summary="真实 diff。",
                metadata_json=evidence_metadata,
                idempotency_key="pr-gate:diff",
                media_type="text/x-diff",
            ),
            "test": artifacts.create_json(
                task_id=task.id,
                artifact_type="test_report",
                display_name="test.json",
                content={"passed": True},
                producer_type=ArtifactProducerType.SYSTEM,
                summary="测试通过。",
                metadata_json={
                    **evidence_metadata,
                    "passed": True,
                },
                idempotency_key="pr-gate:test",
            ),
            "review": artifacts.create_json(
                task_id=task.id,
                artifact_type="review_report",
                display_name="review.json",
                content={"verdict": "approved"},
                producer_type=ArtifactProducerType.SYSTEM,
                summary="Review 通过。",
                metadata_json={
                    **evidence_metadata,
                    "verdict": "approved",
                },
                idempotency_key="pr-gate:review",
            ),
            "security": artifacts.create_json(
                task_id=task.id,
                artifact_type="security_report",
                display_name="security.json",
                content={"blocking": False},
                producer_type=ArtifactProducerType.SYSTEM,
                summary="Security 无阻断。",
                metadata_json={
                    **evidence_metadata,
                    "blocking": False,
                },
                idempotency_key="pr-gate:security",
            ),
        }
        records = PullRequestRecordService(session)

        with pytest.raises(ServiceError) as stale_error:
            records.create(
                pr_payload(
                    task,
                    project,
                    old_plan,
                    evidence,
                    "stale",
                )
            )
        assert stale_error.value.code == (
            "development_plan_not_current_approved"
        )

        with pytest.raises(ServiceError) as approval_error:
            records.create(
                pr_payload(
                    task,
                    project,
                    latest_plan,
                    evidence,
                    "unapproved",
                )
            )
        assert approval_error.value.code == (
            "development_plan_not_current_approved"
        )

        latest_plan.status = "approved"
        session.flush()
        security_metadata = dict(evidence["security"].metadata_json)
        evidence["security"].metadata_json = {
            **security_metadata,
            "evidence_set_id": "pr-gate:cycle:other",
        }
        session.flush()
        with pytest.raises(ServiceError) as evidence_error:
            records.create(
                pr_payload(
                    task,
                    project,
                    latest_plan,
                    evidence,
                    "mismatched-evidence",
                )
            )
        assert evidence_error.value.code == (
            "pull_request_evidence_set_mismatch"
        )

        evidence["security"].metadata_json = security_metadata
        session.flush()
        record = records.create(
            pr_payload(
                task,
                project,
                latest_plan,
                evidence,
                "approved",
            )
        )
        assert record.development_plan_id == latest_plan.id
