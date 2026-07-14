"""M6 Git finalize 证据门禁、单 turn 与 commit 恢复白盒测试。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.providers import ProviderToolCall
from cloudhelm_agent_runtime.schemas.agent_io import (
    ChangedFile,
    CommandExecution,
)
from cloudhelm_agent_runtime.schemas.implementation import CoderAgentOutput
from cloudhelm_agent_runtime.schemas.review_report import (
    AcceptanceReview,
    ReviewerAgentOutput,
)
from cloudhelm_agent_runtime.schemas.security_report import SecurityAgentOutput
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentOutput
from cloudhelm_tool_gateway import create_default_gateway

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.schemas.local_execution_recipe import (
    LocalExecutionRecipe,
)
from cloudhelm_platform_api.services.agent_tool_executor import AgentToolExecutor
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_git_service import (
    LocalDevelopmentGitService,
)


@dataclass(slots=True)
class GitFinalizeSeed:
    """一套真实 Git workspace、数据库证据和 finalize 上下文。"""

    context: LocalDevelopmentContext
    settings: Settings
    gateway: object
    repo: Path
    security_artifact: Artifact


def test_finalize_uses_one_turn_and_exact_tool_call_records(
    tmp_path: Path,
) -> None:
    """成功收尾只增加一个 turn，并精确引用 branch/commit ToolCall。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        seed = _seed(session, tmp_path, "single-turn")
        result = LocalDevelopmentGitService(
            session,
            seed.settings,
            seed.gateway,
        ).finalize(seed.context)
        session.commit()

        assert result.target_phase == "PullRequestCreated"
        assert [call.tool_name for call in result.tool_calls] == [
            "git.status",
            "git.diff",
            "git.commit",
            "git.format_patch",
        ]
        commit_call = next(
            call
            for call in result.tool_calls
            if call.tool_name == "git.commit"
        )
        assert result.pull_request_record is not None
        assert (
            result.pull_request_record.commit_tool_call_id
            == commit_call.id
        )
        assert result.pull_request_record.branch_tool_call_id is not None
        assert result.gate_evidence["recovered_commit"] is False
        assert _git(seed.repo, "rev-list", "--count", "HEAD") == "2"

        conversation = session.scalar(
            select(AgentConversation).where(
                AgentConversation.task_id == seed.context.task.id,
                AgentConversation.source_type == "root",
            )
        )
        assert conversation is not None
        assert conversation.turn_count == 1
        assert [
            item["name"]
            for item in conversation.items_json
            if item["type"] == "function_call"
        ] == [
            "git.status",
            "git.diff",
            "git.commit",
            "git.format_patch",
        ]
        patch = result.artifacts[0]
        assert patch.metadata_json["development_plan_id"] == str(
            seed.context.plan.id
        )
        assert patch.metadata_json["recipe_sha256"] == (
            seed.context.recipe_sha256
        )
        assert patch.metadata_json["evidence_set_id"].startswith("m6:")


def test_gate_failure_happens_before_git_commit(tmp_path: Path) -> None:
    """Security metadata 漂移时，commit 副作用前即拒绝。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        seed = _seed(session, tmp_path, "gate-failure")
        seed.security_artifact.metadata_json = {
            **seed.security_artifact.metadata_json,
            "blocking": True,
        }
        session.commit()

        with pytest.raises(ServiceError) as raised:
            LocalDevelopmentGitService(
                session,
                seed.settings,
                seed.gateway,
            ).finalize(seed.context)

        assert raised.value.code == "m6_security_gate_blocked"
        commit_count = session.scalar(
            select(func.count())
            .select_from(ToolCall)
            .where(
                ToolCall.task_id == seed.context.task.id,
                ToolCall.tool_name == "git.commit",
            )
        )
        assert commit_count == 0
        assert _git(seed.repo, "rev-list", "--count", "HEAD") == "1"


def test_gate_is_reloaded_immediately_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只读 diff 后证据发生漂移时，第二次门禁读取阻止 commit。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        seed = _seed(session, tmp_path, "gate-reload")
        service = LocalDevelopmentGitService(
            session,
            seed.settings,
            seed.gateway,
        )
        execute = service.git.execute

        def execute_with_drift(*args, **kwargs):
            result = execute(*args, **kwargs)
            tool_name = args[3]
            if tool_name == "git.diff":
                seed.security_artifact.metadata_json = {
                    **seed.security_artifact.metadata_json,
                    "blocking": True,
                }
                session.commit()
            return result

        monkeypatch.setattr(service.git, "execute", execute_with_drift)
        with pytest.raises(ServiceError) as raised:
            service.finalize(seed.context)

        assert raised.value.code == "m6_security_gate_blocked"
        assert _count(
            session,
            ToolCall,
            ToolCall.task_id == seed.context.task.id,
            ToolCall.tool_name == "git.commit",
        ) == 0
        assert _git(seed.repo, "rev-list", "--count", "HEAD") == "1"


def test_retry_reuses_commit_after_late_transaction_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """commit 已落地而 PR 事务失败时，重试复用 HEAD 且只建一个 record。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        seed = _seed(session, tmp_path, "recovery")
        first = LocalDevelopmentGitService(
            session,
            seed.settings,
            seed.gateway,
        )

        def fail_record(_data):
            raise ServiceError(
                "m6_injected_transaction_failure",
                "注入 PR record 事务失败。",
                500,
            )

        monkeypatch.setattr(first.persistence.records, "create", fail_record)
        with pytest.raises(ServiceError) as raised:
            first.finalize(seed.context)
        assert raised.value.code == "m6_injected_transaction_failure"
        assert _git(seed.repo, "rev-list", "--count", "HEAD") == "2"
        assert _count(session, PullRequestRecord) == 0
        assert _count(
            session,
            Artifact,
            Artifact.artifact_type == "format_patch",
        ) == 0

        session.refresh(seed.context.task)
        seed.context.task.status = "running"
        seed.context.task.current_phase = "ReadyForPR"
        session.commit()
        recovered = LocalDevelopmentGitService(
            session,
            seed.settings,
            seed.gateway,
        ).finalize(seed.context)
        session.commit()

        assert recovered.gate_evidence["recovered_commit"] is True
        assert _git(seed.repo, "rev-list", "--count", "HEAD") == "2"
        assert _count(session, PullRequestRecord) == 1
        commit_call = next(
            call
            for call in recovered.tool_calls
            if call.tool_name == "git.commit"
        )
        assert commit_call.result_json is not None
        assert commit_call.result_json["reused"] is True
        conversation = session.scalar(
            select(AgentConversation).where(
                AgentConversation.task_id == seed.context.task.id,
                AgentConversation.source_type == "root",
            )
        )
        assert conversation is not None
        assert conversation.turn_count == 2


def _seed(
    session: Session,
    tmp_path: Path,
    label: str,
) -> GitFinalizeSeed:
    """准备真实仓库、Coder branch/diff 与三类通过的质量报告。"""

    settings = Settings(
        m6_workspace_root=str(tmp_path / "workspaces"),
        m6_sample_repo_root=str(tmp_path / "sample"),
        m6_recipe_root=str(tmp_path / "recipes"),
        artifact_root=str(tmp_path / "artifacts"),
        tool_workspace_roots=[str(tmp_path)],
    )
    gateway = create_default_gateway(
        allowed_workspace_roots=settings.effective_tool_workspace_roots,
    )
    project = Project(
        name=f"M6 Git {label}",
        repo_url="fixture://sample-repo-python",
        default_branch="main",
        provider="local",
    )
    session.add(project)
    session.flush()
    task = Task(
        project_id=project.id,
        title=f"M6 Git finalize {label}",
        description="验证真实 Git finalize 收尾。",
        source_type="issue",
        source_ref="demo-issues/test.md",
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
        source_type="issue",
        raw_input="更新 app.py。",
        constraints_json=[],
        acceptance_criteria_json=[
            {
                "id": "AC-001",
                "description": "VALUE 更新为 2。",
                "verification": "pytest",
            }
        ],
        status="approved",
        version=1,
    )
    session.add(requirement)
    session.flush()
    design = TechnicalDesign(
        task_id=task.id,
        requirement_spec_id=requirement.id,
        design_type="m6-git-test",
        content_markdown="# M6 Git",
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
        summary="完成本地代码、测试、评审、安全与 PR record。",
        steps_json=[
            {
                "id": "STEP-001",
                "execution_recipe": "test-finalize",
            }
        ],
        risks_json=[],
        status="approved",
        version=1,
    )
    session.add(plan)
    session.flush()

    repo = Path(settings.m6_workspace_root) / str(task.id) / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "CloudHelm Test")
    _git(repo, "config", "user.email", "cloudhelm@example.test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "chore: baseline")

    coder = _run(
        session,
        task,
        "coder",
        "run_coder",
        "coder_agent_output",
    )
    branch_name = f"codex/task-{str(task.id)[:8]}"
    executor = AgentToolExecutor(
        session,
        gateway,
        settings,
        task_id=task.id,
        agent_run_id=coder.id,
        workflow_step="run_coder",
        attempt=1,
        approved_calls=[
            ("git.create_branch", {"branch_name": branch_name}),
            ("git.diff", {"include_untracked": True}),
        ],
    )
    branch = executor(
        ProviderToolCall(
            call_id=f"call_{label}_branch",
            name="git.create_branch",
            arguments={
                "branch_name": branch_name,
            },
        )
    )
    assert branch.status == "succeeded"
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    diff = executor(
        ProviderToolCall(
            call_id=f"call_{label}_diff",
            name="git.diff",
            arguments={"include_untracked": True},
        )
    )
    assert diff.status == "succeeded"
    diff_details = diff.result["result_json"]
    changed = ChangedFile(
        path="app.py",
        operation="updated",
        intent="更新演示值。",
    )
    coder_output = CoderAgentOutput(
        task_id=task.id,
        development_plan_id=plan.id,
        step_ids=["STEP-001"],
        summary="实现完成。",
        status="completed",
        branch_name=branch_name,
        diff_paths=["app.py"],
        changed_files=[changed],
        risk_level="L1",
    )
    coder.status = "succeeded"
    coder.structured_output_json = coder_output.model_dump(mode="json")
    coder.finished_at = utc_now()
    evidence_set_id = f"m6:{plan.id}:{coder.id}"
    artifacts = ArtifactService(session, settings)
    artifacts.create_text(
        task_id=task.id,
        artifact_type="diff_patch",
        display_name="implementation.diff",
        content=diff_details["patch"],
        producer_type=ArtifactProducerType.TOOL,
        summary="真实 Coder diff。",
        metadata_json={
            "development_plan_id": str(plan.id),
            "recipe_sha256": "sha256:" + ("a" * 64),
            "evidence_set_id": evidence_set_id,
            "coder_agent_run_id": str(coder.id),
            "changed_files": ["app.py"],
        },
        idempotency_key=f"m6:diff:{coder.id}",
        tool_call_id=executor.tool_calls[-1].id,
        media_type="text/x-diff",
    )

    test_run, test_output = _test_run(session, task, plan, changed)
    review_run, review_output = _review_run(session, task, plan, changed)
    security_run, security_output = _security_run(
        session,
        task,
        plan,
    )
    common = {
        "development_plan_id": str(plan.id),
        "recipe_sha256": "sha256:" + ("a" * 64),
        "evidence_set_id": evidence_set_id,
        "coder_agent_run_id": str(coder.id),
    }
    artifacts.create_json(
        task_id=task.id,
        artifact_type="test_report",
        display_name="test-report.json",
        content=test_output,
        producer_type=ArtifactProducerType.AGENT,
        summary="pytest 通过。",
        metadata_json={
            **common,
            "tester_agent_run_id": str(test_run.id),
            "passed": True,
        },
        idempotency_key=f"m6:test-report:{test_run.id}",
        agent_run_id=test_run.id,
    )
    artifacts.create_json(
        task_id=task.id,
        artifact_type="review_report",
        display_name="review-report.json",
        content=review_output,
        producer_type=ArtifactProducerType.AGENT,
        summary="Review 批准。",
        metadata_json={
            **common,
            "reviewer_agent_run_id": str(review_run.id),
            "verdict": "approved",
        },
        idempotency_key=f"m6:review-report:{review_run.id}",
        agent_run_id=review_run.id,
    )
    security_artifact = artifacts.create_json(
        task_id=task.id,
        artifact_type="security_report",
        display_name="security-report.json",
        content=security_output,
        producer_type=ArtifactProducerType.AGENT,
        summary="Security 无阻断。",
        metadata_json={
            **common,
            "security_agent_run_id": str(security_run.id),
            "verdict": "passed",
            "blocking": False,
        },
        idempotency_key=f"m6:security-report:{security_run.id}",
        agent_run_id=security_run.id,
    )
    session.commit()

    recipe = LocalExecutionRecipe.model_validate(
        {
            "schema_version": "1.0",
            "recipe_id": "test-finalize",
            "template_id": "sample-repo-python",
            "issue_path": "demo-issues/test.md",
            "implementation_goal": "更新 app.py。",
            "step_ids": ["STEP-001"],
            "planned_changes": [
                {
                    "path": "app.py",
                    "operation": "update",
                    "purpose": "更新演示值。",
                    "content": "VALUE = 2\n",
                }
            ],
            "test_commands": [
                {
                    "tool_name": "test.run_pytest",
                    "purpose": "运行测试。",
                    "arguments": {},
                }
            ],
            "security_commands": [
                {
                    "tool_name": "security.run_bandit",
                    "purpose": "运行安全扫描。",
                    "arguments": {"path": "."},
                }
            ],
            "acceptance_evidence": [
                {
                    "criterion_id": "AC-001",
                    "notes": "pytest 覆盖。",
                }
            ],
        }
    )
    context = LocalDevelopmentContext(
        task=task,
        project=project,
        requirement=requirement,
        design=design,
        plan=plan,
        recipe=recipe,
        recipe_sha256="sha256:" + ("a" * 64),
    )
    return GitFinalizeSeed(
        context=context,
        settings=settings,
        gateway=gateway,
        repo=repo,
        security_artifact=security_artifact,
    )


def _run(
    session: Session,
    task: Task,
    agent_type: str,
    workflow_step: str,
    output_type: str,
) -> AgentRun:
    """创建符合 M6 workflow identity 约束的 running AgentRun。"""

    run = AgentRun(
        task_id=task.id,
        agent_type=agent_type,
        status="running",
        workflow_step=workflow_step,
        attempt=1,
        idempotency_key=f"m6:{workflow_step}:1",
        model_name="local-rules-m6-v1",
        prompt_hash="m6-test",
        structured_output_type=output_type,
    )
    session.add(run)
    session.flush()
    return run


def _test_run(session, task, plan, changed):
    """创建通过的 Tester 输出。"""

    run = _run(
        session,
        task,
        "tester",
        "run_tester",
        "tester_agent_output",
    )
    output = TesterAgentOutput(
        task_id=task.id,
        development_plan_id=plan.id,
        summary="1 项测试通过。",
        status="passed",
        commands=[
            CommandExecution(
                call_id="call-test",
                command=["uv", "run", "pytest", "-q"],
                purpose="运行 pytest。",
                status="succeeded",
                exit_code=0,
                passed_count=1,
                failed_count=0,
            )
        ],
        passed_count=1,
        failed_count=0,
        skipped_count=0,
        acceptance_results=[
            {
                "criterion_id": "AC-001",
                "status": "passed",
                "evidence_refs": ["artifact://junit"],
                "notes": "pytest 通过。",
            }
        ],
        risk_level="L1",
    ).model_dump(mode="json")
    run.status = "succeeded"
    run.structured_output_json = output
    run.finished_at = utc_now()
    return run, output


def _review_run(session, task, plan, changed):
    """创建批准的 Reviewer 输出。"""

    run = _run(
        session,
        task,
        "reviewer",
        "run_reviewer",
        "reviewer_agent_output",
    )
    output = ReviewerAgentOutput(
        task_id=task.id,
        development_plan_id=plan.id,
        summary="全部验收标准满足。",
        verdict="approved",
        acceptance_results=[
            AcceptanceReview(
                criterion_id="AC-001",
                status="satisfied",
                evidence_refs=["artifact://test"],
                notes="测试通过。",
            )
        ],
        changed_files=[changed],
        proceed_to_security=True,
        risk_level="L1",
    ).model_dump(mode="json")
    run.status = "succeeded"
    run.structured_output_json = output
    run.finished_at = utc_now()
    return run, output


def _security_run(session, task, plan):
    """创建无阻断的 Security 输出。"""

    run = _run(
        session,
        task,
        "security",
        "run_security",
        "security_agent_output",
    )
    output = SecurityAgentOutput(
        task_id=task.id,
        development_plan_id=plan.id,
        summary="扫描通过。",
        verdict="passed",
        scanners=[
            CommandExecution(
                call_id="call-security",
                command=["uv", "run", "bandit", "-r", "."],
                purpose="运行 Bandit。",
                status="succeeded",
                exit_code=0,
            )
        ],
        findings=[],
        remaining_risks=[],
        blocking=False,
        risk_level="L1",
    ).model_dump(mode="json")
    run.status = "succeeded"
    run.structured_output_json = output
    run.finished_at = utc_now()
    return run, output


def _git(repo: Path, *args: str) -> str:
    """以 UTF-8 执行测试仓库 Git 命令并返回 stdout。"""

    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _count(session: Session, model, *criteria) -> int:
    """统计测试记录，可附加过滤条件。"""

    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(session.scalar(statement) or 0)
