"""M6 Artifact 与 PullRequestRecord repository 集成测试。"""

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.repositories.pull_request_record_repository import (
    PullRequestRecordRepository,
)
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)


def test_artifact_and_pull_request_record_repositories() -> None:
    """真实 PostgreSQL 中创建、幂等查询并分页读取 M6 记录。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        project = Project(
            name="M6 repository 项目",
            repo_url="local://sample-repo-python",
            default_branch="main",
            provider="local",
        )
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title="验证 M6 repository",
            description="创建 Artifact 与本地等价 PR record。",
            source_type="manual",
            status="running",
            risk_level="L1",
            current_phase="ReadyForPR",
            created_by="pytest",
        )
        session.add(task)
        session.flush()
        requirement = RequirementSpec(
            task_id=task.id,
            project_id=project.id,
            source_type="manual",
            raw_input="验证 M6 repository。",
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
            design_type="m6",
            content_markdown="# M6",
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
            summary="M6 计划",
            steps_json=[{"id": "STEP-001"}],
            risks_json=[],
            status="approved",
            version=1,
        )
        session.add(plan)
        session.flush()

        artifacts = ArtifactRepository(session)
        created = []
        for index, artifact_type in enumerate(
            (
                "diff_patch",
                "test_report",
                "review_report",
                "security_report",
            ),
            start=1,
        ):
            created.append(
                artifacts.create(
                    Artifact(
                        task_id=task.id,
                        producer_type="system",
                        artifact_type=artifact_type,
                        status="available",
                        display_name=f"{artifact_type}.json",
                        media_type="application/json",
                        storage_key=f"tasks/{task.id}/{artifact_type}.json",
                        sha256=f"sha256:{index:064x}",
                        size_bytes=index,
                        summary=artifact_type,
                        metadata_json={"index": index},
                        idempotency_key=f"artifact:{artifact_type}:1",
                    )
                )
            )

        records = PullRequestRecordRepository(session)
        record = records.create(
            PullRequestRecord(
                task_id=task.id,
                project_id=project.id,
                development_plan_id=plan.id,
                provider="local",
                status="open",
                title="feat: M6 repository",
                summary="门禁通过。",
                base_branch="main",
                head_branch="feature/m6-repository",
                base_commit_sha="a" * 40,
                commit_sha="b" * 40,
                changed_files_json=[{"path": "src/sample_service/main.py"}],
                diff_stat_json={"files": 1, "insertions": 5, "deletions": 0},
                diff_artifact_id=created[0].id,
                test_artifact_id=created[1].id,
                review_artifact_id=created[2].id,
                security_artifact_id=created[3].id,
                idempotency_key="pr-record:commit-b",
            )
        )
        session.commit()

        assert artifacts.get_by_task_idempotency_key(
            task.id,
            "artifact:test_report:1",
        ).id == created[1].id
        latest_security = artifacts.latest_by_task_and_type(
            task.id,
            "security_report",
            status="available",
        )
        assert latest_security is not None
        assert latest_security.id == created[3].id
        artifact_page, artifact_cursor = artifacts.list_by_task(
            task.id,
            2,
            None,
        )
        assert len(artifact_page) == 2
        assert artifact_cursor == "2"

        assert records.get_by_task_commit(task.id, "b" * 40).id == record.id
        assert records.get_by_task_idempotency_key(
            task.id,
            "pr-record:commit-b",
        ).id == record.id
        assert records.latest_by_task(task.id).id == record.id
        record_page, next_cursor = records.list_by_task(
            task.id,
            10,
            None,
            status="open",
        )
        assert [item.id for item in record_page] == [record.id]
        assert next_cursor is None


def test_workflow_agent_run_and_provider_tool_call_repositories() -> None:
    """按 step/attempt 和供应商 call_id 读取 M6 执行记录。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        project = Project(
            name="M6 workflow repository 项目",
            repo_url="local://sample-repo-python",
            default_branch="main",
            provider="local",
        )
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title="验证 M6 workflow repository",
            description="验证步骤幂等、重试序号和供应商 call_id。",
            source_type="manual",
            status="running",
            risk_level="L1",
            current_phase="Implementing",
            created_by="pytest",
        )
        session.add(task)
        session.flush()

        agent_runs = AgentRunRepository(session)
        first_run = agent_runs.create(
            AgentRun(
                task_id=task.id,
                agent_type="coder",
                status="failed",
                workflow_step="run_coder",
                attempt=1,
                idempotency_key=f"{task.id}:run_coder:1",
                error_code="tool_failed",
            )
        )
        active_run = agent_runs.create(
            AgentRun(
                task_id=task.id,
                agent_type="coder",
                status="running",
                workflow_step="run_coder",
                attempt=2,
                idempotency_key=f"{task.id}:run_coder:2",
            )
        )

        tool_calls = ToolCallRepository(session)
        tool_call = tool_calls.create(
            ToolCall(
                task_id=task.id,
                agent_run_id=active_run.id,
                tool_name="repo.write_file",
                provider_call_id="call-m6-write-1",
                provider_item_type="function_call",
                risk_level="L1",
                arguments_json={"path": "src/sample_service/main.py"},
                audit_json={"parameters_hash": "sha256:test"},
                status="running",
                idempotency_key=f"{task.id}:run_coder:2:call-m6-write-1",
            )
        )
        session.commit()

        assert agent_runs.get_by_task_idempotency_key(
            task.id,
            f"{task.id}:run_coder:1",
        ).id == first_run.id
        assert agent_runs.next_attempt(task.id, "run_coder") == 3
        assert agent_runs.active_workflow_run(
            task.id,
            "run_coder",
        ).id == active_run.id
        assert tool_calls.get_by_agent_provider_call(
            active_run.id,
            "call-m6-write-1",
        ).id == tool_call.id
