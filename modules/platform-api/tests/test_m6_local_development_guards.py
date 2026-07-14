"""M6 start/run-next 运行态、并发和副作用门禁。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.services.agent_run_lifecycle import (
    AgentRunLifecycle,
)
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContextResolver,
)
from cloudhelm_platform_api.services.local_development_result import (
    LocalDevelopmentResult,
)
from cloudhelm_platform_api.services.local_development_service import (
    LocalDevelopmentService,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RECIPE_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "sample-repo-python"
    / "demo-issues"
    / "demo-issue-001-auth-profile-v1.plan.json"
)


@pytest.mark.parametrize(
    ("task_action", "error_code"),
    (("pause", "task_paused"), ("cancel", "task_terminal")),
)
def test_start_rejects_paused_and_cancelled_without_side_effects(
    client: TestClient,
    task_action: str,
    error_code: str,
) -> None:
    """start 在暂停/取消后不写 M6 Agent、Tool、Artifact 或事件。"""

    task_id = _seed_approved_m6_task(f"start-{task_action}")
    action = client.post(f"/api/tasks/{task_id}/{task_action}")
    assert action.status_code == 200, action.text
    before = _side_effect_counts(client, task_id)

    response = client.post(
        f"/api/tasks/{task_id}/local-development/start"
    )

    assert response.status_code == 409
    assert response.json()["code"] == error_code
    assert _side_effect_counts(client, task_id) == before
    expected_phase = "Planning"
    assert client.get(f"/api/tasks/{task_id}").json()["current_phase"] == (
        expected_phase
    )


@pytest.mark.parametrize(
    ("task_action", "error_code"),
    (("pause", "task_paused"), ("cancel", "task_terminal")),
)
def test_run_next_rejects_paused_and_cancelled_without_side_effects(
    client: TestClient,
    task_action: str,
    error_code: str,
) -> None:
    """start 后暂停/取消会阻止 Scaffold 文件与 Git 副作用。"""

    task_id = _seed_approved_m6_task(f"run-next-{task_action}")
    started = client.post(
        f"/api/tasks/{task_id}/local-development/start"
    )
    assert started.status_code == 200, started.text
    action = client.post(f"/api/tasks/{task_id}/{task_action}")
    assert action.status_code == 200, action.text
    before = _side_effect_counts(client, task_id)

    response = client.post(
        f"/api/tasks/{task_id}/local-development/run-next"
    )

    assert response.status_code == 409
    assert response.json()["code"] == error_code
    assert _side_effect_counts(client, task_id) == before
    expected_phase = "Scaffolding"
    assert client.get(f"/api/tasks/{task_id}").json()["current_phase"] == (
        expected_phase
    )


def test_run_next_rejects_existing_active_agent_run(
    client: TestClient,
) -> None:
    """同一 Task 已有 running AgentRun 时不启动第二个 Agent。"""

    task_id = _seed_approved_m6_task("active-run")
    assert client.post(
        f"/api/tasks/{task_id}/local-development/start"
    ).status_code == 200
    with Session(get_engine()) as session:
        session.add(
            AgentRun(
                task_id=UUID(task_id),
                agent_type="scaffold",
                status="running",
                workflow_step="existing_active_run",
                attempt=1,
                idempotency_key=f"active:{task_id}",
            )
        )
        session.commit()
    before = _side_effect_counts(client, task_id)

    response = client.post(
        f"/api/tasks/{task_id}/local-development/run-next"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "local_development_step_active"
    assert _side_effect_counts(client, task_id) == before
    assert client.get(f"/api/tasks/{task_id}").json()["current_phase"] == (
        "Scaffolding"
    )


def test_phase_change_during_step_rejects_late_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工具执行后 phase 漂移时不提交本轮 Artifact/PR 或目标阶段。"""

    task_id = _seed_approved_m6_task("phase-changed")
    assert client.post(
        f"/api/tasks/{task_id}/local-development/start"
    ).status_code == 200
    with Session(get_engine(), expire_on_commit=False) as artifact_session:
        artifact_service = ArtifactService(artifact_session)
        committed_artifact = artifact_service.create_text(
            task_id=UUID(task_id),
            artifact_type="diff_patch",
            display_name="committed.diff",
            content="already committed evidence",
            producer_type=ArtifactProducerType.SYSTEM,
            summary="已提交证据。",
            metadata_json={},
            idempotency_key=f"committed:{task_id}",
            media_type="text/x-diff",
        )
        artifact_service.commit()
        committed_artifact_id = committed_artifact.id
    before = _side_effect_counts(client, task_id)

    with Session(get_engine(), expire_on_commit=False) as session:
        service = LocalDevelopmentService(
            session,
            client.app.state.tool_gateway,
        )

        def drift_phase(context, action) -> LocalDevelopmentResult:
            with Session(get_engine()) as concurrent:
                task = concurrent.get(Task, UUID(task_id))
                assert task is not None
                task.current_phase = "Testing"
                concurrent.commit()
            return LocalDevelopmentResult(
                action=action.value,
                message="模拟外部并发推进。",
                target_phase="Implementing",
                artifacts=[committed_artifact],
            )

        monkeypatch.setattr(service, "_dispatch", drift_phase)
        with pytest.raises(ServiceError) as exc_info:
            service.run_next(UUID(task_id), "pytest")

    assert exc_info.value.code == "local_development_phase_changed"
    after = _side_effect_counts(client, task_id)
    assert after["tool_calls"] == before["tool_calls"]
    assert after["artifacts"] == before["artifacts"]
    assert after["pull_requests"] == before["pull_requests"]
    assert after["agent_runs"] == before["agent_runs"] + 1
    assert after["events"] == before["events"] + 2
    failed_run = client.get(
        f"/api/tasks/{task_id}/agent-runs?limit=20"
    ).json()["items"][0]
    assert failed_run["status"] == "failed"
    assert failed_run["error_code"] == "local_development_phase_changed"
    assert client.get(f"/api/tasks/{task_id}").json()["current_phase"] == (
        "Testing"
    )
    retained = client.get(f"/api/artifacts/{committed_artifact_id}")
    assert retained.status_code == 200, retained.text
    assert retained.json()["preview"]["text"] == (
        "already committed evidence"
    )


def test_database_allows_only_one_concurrent_m6_agent_claim() -> None:
    """真实 PostgreSQL partial unique index 原子拒绝双 running claim。"""

    task_id = UUID(_seed_approved_m6_task("concurrent-claim"))
    barrier = Barrier(2)

    def claim() -> tuple[str, str]:
        with Session(get_engine(), expire_on_commit=False) as session:
            task = session.get(Task, task_id)
            assert task is not None
            lifecycle = AgentRunLifecycle(session, get_settings())
            barrier.wait(timeout=10)
            try:
                run = lifecycle.start(
                    task,
                    "scaffold",
                    workflow_step="run_scaffold",
                )
                session.commit()
            except ServiceError as exc:
                return "error", exc.code
            return "success", str(run.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim(), range(2)))

    assert [item[0] for item in results].count("success") == 1
    assert ("error", "local_development_step_active") in results
    with Session(get_engine()) as session:
        active = (
            session.query(AgentRun)
            .filter(
                AgentRun.task_id == task_id,
                AgentRun.workflow_step == "run_scaffold",
                AgentRun.status == "running",
            )
            .all()
        )
        assert len(active) == 1


def test_concurrent_run_next_requests_execute_one_scaffold(
    client: TestClient,
) -> None:
    """两个已通过初始 Task lock 的请求仍只能有一个执行副作用。"""

    task_id = UUID(_seed_approved_m6_task("concurrent-run-next"))
    assert client.post(
        f"/api/tasks/{task_id}/local-development/start"
    ).status_code == 200
    start_barrier = Barrier(2)
    claimed = Event()
    release_winner = Event()

    def run_request() -> tuple[str, str]:
        with Session(get_engine(), expire_on_commit=False) as session:
            service = LocalDevelopmentService(
                session,
                client.app.state.tool_gateway,
            )
            original_dispatch = service._dispatch

            def held_dispatch(*args, **kwargs):
                claimed.set()
                assert release_winner.wait(timeout=15)
                return original_dispatch(*args, **kwargs)

            service._dispatch = held_dispatch
            start_barrier.wait(timeout=10)
            try:
                result = service.run_next(task_id, "pytest")
            except ServiceError as exc:
                assert claimed.wait(timeout=10)
                release_winner.set()
                return "error", exc.code
            finally:
                release_winner.set()
            return "success", result.task.current_phase

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: run_request(), range(2)))

    assert results.count(("success", "Implementing")) == 1
    assert results.count(
        ("error", "local_development_step_active")
    ) == 1
    runs = client.get(
        f"/api/tasks/{task_id}/agent-runs?limit=20"
    ).json()["items"]
    scaffold_runs = [
        item
        for item in runs
        if item["workflow_step"] == "run_scaffold"
    ]
    assert len(scaffold_runs) == 1
    assert scaffold_runs[0]["status"] == "succeeded"
    artifacts = client.get(
        f"/api/tasks/{task_id}/artifacts?artifact_type=workspace_manifest"
    ).json()["items"]
    assert len(artifacts) == 1


def test_state_only_returns_current_plan_and_recipe_evidence(
    client: TestClient,
) -> None:
    """新计划尚未产出证据时，状态聚合不得串入旧计划 Artifact/PR。"""

    task_id = UUID(_seed_approved_m6_task("state-plan-isolation"))
    with Session(get_engine(), expire_on_commit=False) as session:
        first_plan = (
            session.query(DevelopmentPlan)
            .filter(DevelopmentPlan.task_id == task_id)
            .one()
        )
        current_plan = DevelopmentPlan(
            task_id=first_plan.task_id,
            project_id=first_plan.project_id,
            technical_design_id=first_plan.technical_design_id,
            summary="第二版已审批计划，尚未生成完整 M6 证据。",
            steps_json=list(first_plan.steps_json),
            risks_json=[],
            status="approved",
            version=2,
            created_at=first_plan.created_at + timedelta(seconds=1),
            updated_at=first_plan.updated_at + timedelta(seconds=1),
        )
        session.add(current_plan)
        session.flush()
        context = LocalDevelopmentContextResolver(
            session,
            get_settings(),
        ).resolve(task_id)
        assert context.plan.id == current_plan.id

        now = datetime.now(UTC)
        current_diff = _artifact_record(
            task_id,
            current_plan.id,
            context.recipe_sha256,
            "diff_patch",
            "current",
            now,
        )
        old_diff = _artifact_record(
            task_id,
            first_plan.id,
            context.recipe_sha256,
            "diff_patch",
            "old-later",
            now + timedelta(minutes=5),
        )
        old_test = _artifact_record(
            task_id,
            first_plan.id,
            context.recipe_sha256,
            "test_report",
            "old-test",
            now + timedelta(minutes=6),
        )
        old_review = _artifact_record(
            task_id,
            first_plan.id,
            context.recipe_sha256,
            "review_report",
            "old-review",
            now + timedelta(minutes=7),
        )
        old_security = _artifact_record(
            task_id,
            first_plan.id,
            context.recipe_sha256,
            "security_report",
            "old-security",
            now + timedelta(minutes=8),
        )
        stale_recipe_sha256 = f"sha256:{'0' * 64}"
        stale_current_diff = _artifact_record(
            task_id,
            current_plan.id,
            stale_recipe_sha256,
            "diff_patch",
            "stale-current-diff",
            now + timedelta(minutes=10),
        )
        stale_current_test = _artifact_record(
            task_id,
            current_plan.id,
            stale_recipe_sha256,
            "test_report",
            "stale-current-test",
            now + timedelta(minutes=11),
        )
        stale_current_review = _artifact_record(
            task_id,
            current_plan.id,
            stale_recipe_sha256,
            "review_report",
            "stale-current-review",
            now + timedelta(minutes=12),
        )
        stale_current_security = _artifact_record(
            task_id,
            current_plan.id,
            stale_recipe_sha256,
            "security_report",
            "stale-current-security",
            now + timedelta(minutes=13),
        )
        session.add_all(
            [
                current_diff,
                old_diff,
                old_test,
                old_review,
                old_security,
                stale_current_diff,
                stale_current_test,
                stale_current_review,
                stale_current_security,
            ]
        )
        session.flush()
        old_pr = PullRequestRecord(
            task_id=task_id,
            project_id=first_plan.project_id,
            development_plan_id=first_plan.id,
            provider="local",
            status="open",
            title="旧计划本地等价 PR",
            summary="该记录不得进入新计划状态聚合。",
            base_branch="main",
            head_branch="codex/old-plan",
            base_commit_sha="1" * 40,
            commit_sha="2" * 40,
            changed_files_json=[{"path": "src/old.py"}],
            diff_stat_json={"files": 1},
            diff_artifact_id=old_diff.id,
            test_artifact_id=old_test.id,
            review_artifact_id=old_review.id,
            security_artifact_id=old_security.id,
            idempotency_key=f"old-plan-pr:{task_id}",
            created_at=now + timedelta(minutes=9),
            updated_at=now + timedelta(minutes=9),
        )
        stale_current_pr = PullRequestRecord(
            task_id=task_id,
            project_id=current_plan.project_id,
            development_plan_id=current_plan.id,
            provider="local",
            status="open",
            title="当前计划旧 recipe 本地等价 PR",
            summary="recipe 内容变化后该记录也不得进入状态聚合。",
            base_branch="main",
            head_branch="codex/stale-recipe",
            base_commit_sha="1" * 40,
            commit_sha="3" * 40,
            changed_files_json=[{"path": "src/stale.py"}],
            diff_stat_json={"files": 1},
            diff_artifact_id=stale_current_diff.id,
            test_artifact_id=stale_current_test.id,
            review_artifact_id=stale_current_review.id,
            security_artifact_id=stale_current_security.id,
            idempotency_key=f"stale-recipe-pr:{task_id}",
            created_at=now + timedelta(minutes=14),
            updated_at=now + timedelta(minutes=14),
        )
        session.add_all([old_pr, stale_current_pr])
        session.commit()
        current_plan_id = current_plan.id
        current_diff_id = current_diff.id
        old_diff_id = old_diff.id

    response = client.get(f"/api/tasks/{task_id}/local-development")

    assert response.status_code == 200, response.text
    state = response.json()
    assert state["development_plan_id"] == str(current_plan_id)
    assert state["latest_artifact_ids"] == {
        "diff_patch": str(current_diff_id)
    }
    assert str(old_diff_id) not in state["latest_artifact_ids"].values()
    assert state["latest_pull_request_record_id"] is None


def _seed_approved_m6_task(label: str) -> str:
    """直接准备合法审批链，把测试重点限制在 HTTP 运行态门禁。"""

    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    criteria = [
        {
            "id": item["criterion_id"],
            "description": item["notes"],
            "verification": "pytest",
            "status": "pending",
        }
        for item in recipe["acceptance_evidence"]
    ]
    with Session(get_engine(), expire_on_commit=False) as session:
        project = Project(
            name=f"M6 guard {label}",
            repo_url="fixture://sample-repo-python",
            default_branch="main",
            provider="local",
        )
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title=f"M6 guard {label}",
            description="验证 M6 运行态和并发门禁。",
            source_type="issue",
            source_ref=recipe["issue_path"],
            status="running",
            risk_level="L1",
            current_phase="Planning",
            created_by="pytest",
        )
        session.add(task)
        session.flush()
        requirement = RequirementSpec(
            task_id=task.id,
            project_id=project.id,
            source_type="issue",
            raw_input=task.description,
            user_story="验证本地开发副作用门禁。",
            constraints_json=[{"type": "test", "value": "M6", "required": True}],
            acceptance_criteria_json=criteria,
            status="approved",
            version=1,
        )
        session.add(requirement)
        session.flush()
        design = TechnicalDesign(
            task_id=task.id,
            requirement_spec_id=requirement.id,
            design_type="m6-guard",
            content_markdown="# M6 guard",
            risk_level="L1",
            status="approved",
            version=1,
        )
        session.add(design)
        session.flush()
        session.add(
            DevelopmentPlan(
                task_id=task.id,
                project_id=project.id,
                technical_design_id=design.id,
                summary="执行受控 M6 recipe。",
                steps_json=[
                    {
                        "id": recipe["step_ids"][0],
                        "execution_recipe": recipe["recipe_id"],
                    }
                ],
                risks_json=[],
                status="approved",
                version=1,
            )
        )
        session.commit()
        return str(task.id)


def _artifact_record(
    task_id: UUID,
    plan_id: UUID,
    recipe_sha256: str,
    artifact_type: str,
    suffix: str,
    created_at: datetime,
) -> Artifact:
    """构造无需读取物理内容的状态聚合 Artifact 记录。"""

    identity = f"{task_id}:{plan_id}:{artifact_type}:{suffix}"
    return Artifact(
        task_id=task_id,
        producer_type="system",
        artifact_type=artifact_type,
        status="available",
        display_name=f"{suffix}.json",
        media_type="application/json",
        storage_key=f"tests/state-isolation/{identity}.json",
        sha256=f"sha256:{hashlib.sha256(identity.encode()).hexdigest()}",
        size_bytes=2,
        summary="状态聚合隔离测试证据。",
        metadata_json={
            "development_plan_id": str(plan_id),
            "recipe_sha256": recipe_sha256,
        },
        idempotency_key=f"state-isolation:{identity}",
        created_at=created_at,
        updated_at=created_at,
    )


def _side_effect_counts(
    client: TestClient,
    task_id: str,
) -> dict[str, int]:
    """读取失败请求前后必须保持不变的审计资源数量。"""

    paths = {
        "agent_runs": f"/api/tasks/{task_id}/agent-runs?limit=100",
        "tool_calls": f"/api/tasks/{task_id}/tool-calls?limit=100",
        "artifacts": f"/api/tasks/{task_id}/artifacts?limit=100",
        "pull_requests": (
            f"/api/tasks/{task_id}/pull-request-records?limit=100"
        ),
        "events": f"/api/tasks/{task_id}/timeline?limit=100",
    }
    counts = {}
    for name, path in paths.items():
        response = client.get(path)
        assert response.status_code == 200, response.text
        counts[name] = len(response.json()["items"])
    return counts
