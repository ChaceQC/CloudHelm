"""M6 Artifact 与本地 PR record API 测试数据构造器。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordCreate,
)
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.pull_request_record_service import (
    PullRequestRecordService,
)


@dataclass(frozen=True)
class M6EvidenceFixture:
    """一个 Task 的 Artifact 与 PR record 测试引用。"""

    task_id: UUID
    preview_artifact_id: UUID
    invalidated_artifact_id: UUID
    pull_request_record_ids: tuple[UUID, ...]


def seed_m6_evidence(
    label: str,
    *,
    pull_request_count: int,
) -> M6EvidenceFixture:
    """在真实 PostgreSQL 与临时 Artifact root 中准备黑盒读取数据。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        project = Project(
            name=f"M6 API {label}",
            repo_url=f"local://sample-repo-python/{label}",
            default_branch="main",
            provider="local",
        )
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title=f"M6 API {label}",
            description="验证 Artifact 与本地 PR record 查询契约。",
            source_type="manual",
            status="running",
            risk_level="L1",
            current_phase="PullRequestCreated",
            created_by="pytest",
        )
        session.add(task)
        session.flush()
        requirement = RequirementSpec(
            task_id=task.id,
            project_id=project.id,
            source_type="manual",
            raw_input="生成真实本地开发证据。",
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
            design_type="m6-api-test",
            content_markdown="# M6 API",
            risk_level="L1",
            status="approved",
            version=1,
        )
        session.add(design)
        session.flush()
        plan = DevelopmentPlan(
            task_id=task.id,
            project_id=project.id,
            technical_design_id=design.id,
            summary="M6 API 黑盒测试计划",
            steps_json=[{"id": "STEP-001"}],
            risks_json=[],
            status="approved",
            version=1,
        )
        session.add(plan)
        session.flush()

        artifacts = ArtifactService(session)
        evidence_metadata = {
            "evidence_set_id": f"{label}:cycle:1",
            "development_plan_id": str(plan.id),
            "recipe_sha256": (
                "sha256:"
                + hashlib.sha256(label.encode("utf-8")).hexdigest()
            ),
        }
        preview_artifact = artifacts.create_text(
            task_id=task.id,
            artifact_type="diff_patch",
            display_name="changes.patch",
            content=(
                "workspace=D:\\private\\sample\n真实 diff 内容\n"
                + ("x" * 70000)
            ),
            producer_type=ArtifactProducerType.SYSTEM,
            summary="真实 diff 来自 D:\\private\\sample",
            metadata_json={
                **evidence_metadata,
                "workspace_root": r"D:\private\sample",
                "report_path": r"D:\private\sample\changes.patch",
            },
            idempotency_key=f"{label}:diff",
            media_type="text/x-diff",
        )
        test_artifact = artifacts.create_json(
            task_id=task.id,
            artifact_type="test_report",
            display_name="test-report.json",
            content={"status": "passed", "passed_count": 3},
            producer_type=ArtifactProducerType.SYSTEM,
            summary="pytest 通过",
            metadata_json={**evidence_metadata, "passed": True},
            idempotency_key=f"{label}:test",
        )
        review_artifact = artifacts.create_json(
            task_id=task.id,
            artifact_type="review_report",
            display_name="review-report.json",
            content={"verdict": "approved"},
            producer_type=ArtifactProducerType.SYSTEM,
            summary="Review 通过",
            metadata_json={
                **evidence_metadata,
                "verdict": "approved",
            },
            idempotency_key=f"{label}:review",
        )
        security_artifact = artifacts.create_json(
            task_id=task.id,
            artifact_type="security_report",
            display_name="security-report.json",
            content={"verdict": "passed", "blocking": False},
            producer_type=ArtifactProducerType.SYSTEM,
            summary="Security 无阻断",
            metadata_json={**evidence_metadata, "blocking": False},
            idempotency_key=f"{label}:security",
        )
        invalidated_artifact = artifacts.create_text(
            task_id=task.id,
            artifact_type="debug_log",
            display_name="debug.log",
            content="历史调试记录",
            producer_type=ArtifactProducerType.SYSTEM,
            summary="已失效调试记录",
            metadata_json={},
            idempotency_key=f"{label}:invalidated",
        )
        invalidated_artifact.status = "invalidated"

        records = PullRequestRecordService(session)
        created_records = []
        for index in range(1, pull_request_count + 1):
            created_records.append(
                records.create(
                    PullRequestRecordCreate(
                        task_id=task.id,
                        project_id=project.id,
                        development_plan_id=plan.id,
                        title=f"feat: M6 API {label} #{index}",
                        summary="真实 diff、测试、Review 与 Security 门禁通过。",
                        base_branch="main",
                        head_branch=f"codex/{label}-{index}",
                        base_commit_sha=f"{1000 + index:040x}",
                        commit_sha=f"{2000 + index:040x}",
                        changed_files_json=[
                            {
                                "path": "src/sample_service/main.py",
                                "operation": "updated",
                            }
                        ],
                        diff_stat_json={
                            "files": 1,
                            "insertions": index,
                            "deletions": 0,
                        },
                        diff_artifact_id=preview_artifact.id,
                        test_artifact_id=test_artifact.id,
                        review_artifact_id=review_artifact.id,
                        security_artifact_id=security_artifact.id,
                        idempotency_key=f"{label}:pr:{index}",
                    )
                )
            )

        session.commit()
        return M6EvidenceFixture(
            task_id=task.id,
            preview_artifact_id=preview_artifact.id,
            invalidated_artifact_id=invalidated_artifact.id,
            pull_request_record_ids=tuple(
                record.id for record in created_records
            ),
        )
