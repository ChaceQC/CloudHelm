"""Git Tool 测试。"""

from pathlib import Path
from subprocess import run
from uuid import uuid4

from cloudhelm_tool_gateway import RiskLevel, ToolCallRequest, create_default_gateway


def _git(repo: Path, *args: str) -> None:
    """执行测试仓库初始化命令。"""

    completed = run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def _request(tool_name: str, risk_level: RiskLevel, repo: Path, arguments: dict | None = None) -> ToolCallRequest:
    """构造 Git Tool 请求。"""

    return ToolCallRequest(
        task_id=uuid4(),
        agent_run_id=uuid4(),
        agent_type="coder",
        tool_name=tool_name,
        risk_level=risk_level,
        idempotency_key=str(uuid4()),
        arguments={"repo_root": str(repo), **(arguments or {})},
        reason="pytest",
    )


def _repo(tmp_path: Path) -> Path:
    """创建有用户配置的本地 Git 仓库。"""

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "tester@example.com")
    _git(tmp_path, "config", "user.name", "Tester")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_git_status_and_diff(tmp_path: Path) -> None:
    """Git Tool 能读取真实 status 和 diff。"""

    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# demo\nchanged\n", encoding="utf-8")
    gateway = create_default_gateway(allowed_workspace_roots=[repo])
    status = gateway.execute(_request("git.status", RiskLevel.L0, repo))
    diff = gateway.execute(_request("git.diff", RiskLevel.L0, repo))
    assert status.status == "succeeded"
    assert "README.md" in (status.stdout_summary or "")
    assert diff.status == "succeeded"
    assert "changed" in (diff.stdout_summary or "")


def test_git_create_branch_and_commit(tmp_path: Path) -> None:
    """Git Tool 能创建分支并提交显式文件列表。"""

    repo = _repo(tmp_path)
    gateway = create_default_gateway(allowed_workspace_roots=[repo])
    branch = gateway.execute(_request("git.create_branch", RiskLevel.L2, repo, {"branch_name": "feature/m5-test"}))
    assert branch.status == "succeeded"
    (repo / "README.md").write_text("# demo\nm5\n", encoding="utf-8")
    commit = gateway.execute(
        _request("git.commit", RiskLevel.L2, repo, {"message": "test: m5 git commit", "paths": ["README.md"]})
    )
    assert commit.status == "succeeded"
    assert commit.result_json is not None
    assert commit.result_json["commit_hash"]


def test_git_commit_rejects_preexisting_staged_changes(tmp_path: Path) -> None:
    """Git Tool 不得把调用前暂存的无关文件混入提交。"""

    repo = _repo(tmp_path)
    (repo / "unrelated.txt").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")
    (repo / "README.md").write_text("# demo\nrequested\n", encoding="utf-8")

    result = create_default_gateway(allowed_workspace_roots=[repo]).execute(
        _request("git.commit", RiskLevel.L2, repo, {"message": "test: isolated commit", "paths": ["README.md"]})
    )

    assert result.status == "failed"
    assert result.error_code == "git_index_not_clean"


def test_git_commit_rejects_repository_root_pathspec(tmp_path: Path) -> None:
    """Git Tool 不得用 `.` 把整个仓库作为显式文件列表提交。"""

    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# demo\nchanged\n", encoding="utf-8")

    result = create_default_gateway(allowed_workspace_roots=[repo]).execute(
        _request("git.commit", RiskLevel.L2, repo, {"message": "test: reject root", "paths": ["."]})
    )

    assert result.status == "failed"
    assert result.error_code == "git_commit_path_not_file"
