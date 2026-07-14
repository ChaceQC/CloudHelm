"""M6 foundation service 白盒测试辅助。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordCreate,
)


def project_and_task(
    session: Session,
    label: str,
) -> tuple[Project, Task]:
    """创建真实 Project/Task 测试归属。"""

    project = Project(
        name=f"M6 {label}",
        repo_url=f"fixture://{label}",
        default_branch="main",
        provider="local",
    )
    session.add(project)
    session.flush()
    task = Task(
        project_id=project.id,
        title=f"M6 {label}",
        description="M6 foundation service 白盒测试。",
        source_type="manual",
        status="running",
        risk_level="L1",
        current_phase="ReadyForPR",
        created_by="pytest",
    )
    session.add(task)
    session.flush()
    return project, task


def pr_payload(
    task: Task,
    project: Project,
    plan: DevelopmentPlan,
    evidence: dict,
    suffix: str,
) -> PullRequestRecordCreate:
    """构造门禁完整的本地 PR record DTO。"""

    return PullRequestRecordCreate(
        task_id=task.id,
        project_id=project.id,
        development_plan_id=plan.id,
        title=f"feat: {suffix}",
        summary="真实门禁证据。",
        base_branch="main",
        head_branch=f"codex/{suffix}",
        base_commit_sha=f"{1000:040x}",
        commit_sha=f"{uuid4().int % (16 ** 40):040x}",
        changed_files_json=[{"path": "src/sample_service/main.py"}],
        diff_stat_json={"files": 1},
        diff_artifact_id=evidence["diff"].id,
        test_artifact_id=evidence["test"].id,
        review_artifact_id=evidence["review"].id,
        security_artifact_id=evidence["security"].id,
        idempotency_key=f"pr-gate:{suffix}",
    )
