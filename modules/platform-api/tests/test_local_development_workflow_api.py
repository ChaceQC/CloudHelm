"""M6 sample repo 真实本地开发闭环黑盒测试。"""

import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from cloudhelm_platform_api.core.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ISSUE_PATH = (
    REPO_ROOT
    / "examples"
    / "sample-repo-python"
    / "demo-issues"
    / "001-auth-profile.md"
)


def test_local_development_api_completes_real_sample_pr(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """从真实 issue/审批推进到 diff、pytest、安全、commit 和 local PR。"""

    project = client.post(
        "/api/projects",
        json={
            "name": "M6 Sample Fixture",
            "repo_url": "fixture://sample-repo-python",
            "default_branch": "main",
            "provider": "local",
        },
    )
    assert project.status_code == 201, project.text
    task = client.post(
        "/api/tasks",
        json={
            "project_id": project.json()["id"],
            "title": "实现注册、登录与个人资料",
            "description": ISSUE_PATH.read_text(encoding="utf-8"),
            "source_type": "issue",
            "source_ref": "demo-issues/001-auth-profile.md",
            "risk_level": "L1",
            "created_by": "pytest",
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]

    _prepare_and_approve_m4_plan(client, task_id)
    blocked = client.post(
        f"/api/tasks/{task_id}/local-development/start",
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] in {
        "approved_development_plan_missing",
        "task_waiting_approval",
    }

    plan_approval = _latest_pending_plan_approval(client, task_id)
    approved = client.post(
        f"/api/approvals/{plan_approval['id']}/approve",
        json={"actor_id": "pytest", "reason": "批准 M6 execution recipe。"},
    )
    assert approved.status_code == 200, approved.text

    state = client.get(f"/api/tasks/{task_id}/local-development")
    assert state.status_code == 200, state.text
    assert state.json()["next_action"] == "start_local_development"

    started = client.post(
        f"/api/tasks/{task_id}/local-development/start",
        json={"actor_id": "pytest"},
    )
    assert started.status_code == 200, started.text
    assert started.json()["task"]["current_phase"] == "Scaffolding"

    expected = [
        ("run_scaffold", "Implementing"),
        ("run_coder", "Testing"),
        ("run_tester", "Reviewing"),
        ("run_reviewer", "SecurityScanning"),
        ("run_security", "ReadyForPR"),
        ("finalize_local_pull_request", "PullRequestCreated"),
    ]
    responses = []
    for action, phase in expected:
        response = client.post(
            f"/api/tasks/{task_id}/local-development/run-next",
            json={"actor_id": "pytest"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action"] == action
        if payload["task"]["current_phase"] != phase:
            pytest.fail(
                json.dumps(payload, ensure_ascii=False, indent=2),
                pytrace=False,
            )
        responses.append(payload)

    final = responses[-1]
    assert final["task"]["status"] == "running"
    assert final["pull_request_record"]["provider"] == "local"
    assert final["pull_request_record"]["url"] is None
    assert final["pull_request_record"]["commit_sha"]
    assert final["pull_request_record"]["changed_files_json"]

    artifact_page = client.get(
        f"/api/tasks/{task_id}/artifacts?limit=100"
    )
    assert artifact_page.status_code == 200, artifact_page.text
    artifact_types = {
        item["artifact_type"] for item in artifact_page.json()["items"]
    }
    assert {
        "workspace_manifest",
        "diff_patch",
        "junit_xml",
        "test_report",
        "review_report",
        "security_report",
        "format_patch",
    }.issubset(artifact_types)
    _assert_shared_root_conversation(client, task_id)
    _assert_real_git_workspace(task_id)
    _assert_patch_artifacts_apply(task_id, tmp_path)


def _prepare_and_approve_m4_plan(
    client: TestClient,
    task_id: str,
) -> None:
    """通过真实 M4 API 生成 Requirement、Design 和待审批 Plan。"""

    assert client.post(f"/api/tasks/{task_id}/start").status_code == 200
    requirement = client.post(f"/api/tasks/{task_id}/run-next")
    assert requirement.status_code == 200, requirement.text
    criteria = requirement.json()["requirement"]["acceptance_criteria_json"]
    assert [item["id"] for item in criteria] == [
        "AC-AUTH-001",
        "AC-AUTH-002",
        "AC-AUTH-003",
        "AC-AUTH-004",
        "AC-AUTH-005",
        "AC-PROFILE-001",
        "AC-PROFILE-002",
        "AC-PROFILE-003",
        "AC-SEC-001",
        "AC-OBS-001",
        "AC-TEST-001",
    ]
    architect = client.post(f"/api/tasks/{task_id}/run-next")
    assert architect.status_code == 200, architect.text
    design = architect.json()["technical_design"]
    assert set(design["openapi_json"]["paths"]) == {
        "/auth/register",
        "/auth/login",
        "/profile",
    }
    assert design["db_schema_json"]["tables"][0]["name"] == "users"
    assert design["db_schema_json"]["tables"][0]["columns"] == [
        "id TEXT PRIMARY KEY",
        "email TEXT NOT NULL UNIQUE",
        "password_hash TEXT NOT NULL",
        "display_name TEXT NOT NULL",
        "created_at TEXT NOT NULL",
    ]
    if architect.json()["task"]["current_phase"] == "WaitingDesignApproval":
        approval_id = architect.json()["approval"]["id"]
        response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"actor_id": "pytest"},
        )
        assert response.status_code == 200, response.text
    planner = client.post(f"/api/tasks/{task_id}/run-next")
    assert planner.status_code == 200, planner.text
    steps = planner.json()["development_plan"]["steps_json"]
    recipe_steps = [
        item for item in steps if item.get("execution_recipe")
    ]
    assert recipe_steps == [
        {
            **next(item for item in steps if item["id"] == "STEP-002"),
            "execution_recipe": "demo-issue-001-auth-profile-v1",
        }
    ]


def _latest_pending_plan_approval(
    client: TestClient,
    task_id: str,
) -> dict:
    response = client.get(
        f"/api/approvals?task_id={task_id}&status=pending&limit=20"
    )
    assert response.status_code == 200, response.text
    return next(
        item
        for item in response.json()["items"]
        if item["action"] == "approve_development_plan"
    )


def _assert_shared_root_conversation(
    client: TestClient,
    task_id: str,
) -> None:
    response = client.get(f"/api/tasks/{task_id}/agent-runs?limit=50")
    assert response.status_code == 200, response.text
    runs = response.json()["items"]
    normal_roles = {
        "requirement",
        "architect",
        "planner",
        "scaffold",
        "coder",
        "tester",
        "reviewer",
        "security",
    }
    selected = [item for item in runs if item["agent_type"] in normal_roles]
    assert normal_roles.issubset({item["agent_type"] for item in selected})
    conversation_ids = {
        item["conversation_id"]
        for item in selected
        if item["conversation_id"] is not None
    }
    assert len(conversation_ids) == 1


def _assert_real_git_workspace(task_id: str) -> None:
    settings = get_settings()
    workspace = Path(settings.m6_workspace_root) / task_id / "repo"
    status = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain=v1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert status.returncode == 0, status.stderr
    assert status.stdout.strip() == ""
    branch = subprocess.run(
        ["git", "-C", str(workspace), "branch", "--show-current"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert branch.returncode == 0, branch.stderr
    assert branch.stdout.strip().startswith("codex/task-")


def _assert_patch_artifacts_apply(task_id: str, tmp_path: Path) -> None:
    """从完整 M4-M6 闭环产物验证 diff 与 format-patch 均保持 Git 语义。"""

    settings = get_settings()
    workspace = Path(settings.m6_workspace_root) / task_id / "repo"
    artifact_root = Path(settings.artifact_root) / task_id
    patches = [
        *artifact_root.rglob("implementation.diff"),
        *artifact_root.rglob("*.patch"),
    ]
    assert len(patches) == 2

    apply_repo = tmp_path / "m6-e2e-apply-check"
    cloned = subprocess.run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            str(workspace),
            str(apply_repo),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert cloned.returncode == 0, cloned.stderr
    checkout = subprocess.run(
        ["git", "-C", str(apply_repo), "checkout", "main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert checkout.returncode == 0, checkout.stderr
    for patch in patches:
        checked = subprocess.run(
            ["git", "-C", str(apply_repo), "apply", "--check", str(patch)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert checked.returncode == 0, (
            f"{patch.name}: {checked.stderr}"
        )
