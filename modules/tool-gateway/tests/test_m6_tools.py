"""M6 Scaffold、测试、安全和 Git 证据工具白盒测试。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from cloudhelm_tool_gateway import RiskLevel, ToolCallRequest, create_default_gateway
from cloudhelm_tool_gateway.process_runner import ProcessResult
from cloudhelm_tool_gateway.schemas.security import (
    SecurityRunBanditArguments,
    SecurityRunPipAuditArguments,
)
from cloudhelm_tool_gateway.schemas.test_run import (
    TestRunPytestArguments as PytestToolArguments,
)
from cloudhelm_tool_gateway.tools import security_tool, test_tool


def _request(
    tool_name: str,
    risk_level: RiskLevel,
    arguments: dict,
    *,
    agent_type: str,
) -> ToolCallRequest:
    """构造绑定真实 Agent 上下文的工具请求。"""

    return ToolCallRequest(
        task_id=uuid4(),
        agent_run_id=uuid4(),
        agent_type=agent_type,
        tool_name=tool_name,
        risk_level=risk_level,
        idempotency_key=str(uuid4()),
        arguments=arguments,
        reason="M6 工具白盒验证",
    )


def test_registry_exposes_stable_provider_schema_without_bound_roots() -> None:
    """模型工具 schema 必须稳定且不暴露服务端 workspace 字段。"""

    declarations = {
        item["name"]: item
        for item in create_default_gateway().list_tools()
    }
    assert {
        "scaffold.prepare_workspace",
        "test.run_pytest",
        "security.run_bandit",
        "security.run_pip_audit",
        "git.format_patch",
    } <= declarations.keys()
    repo_read = declarations["repo.read_file"]
    assert "workspace_root" in repo_read["arguments_schema"]["properties"]
    assert "workspace_root" not in repo_read["provider_arguments_schema"]["properties"]
    scaffold = declarations["scaffold.prepare_workspace"]
    assert set(scaffold["bound_arguments"]) == {
        "source_root",
        "workspace_root",
        "target_directory",
    }


def test_repo_write_uses_expected_sha256_as_optimistic_lock(tmp_path: Path) -> None:
    """Coder 重试不得覆盖调用后已经变化的文件。"""

    target = tmp_path / "demo.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    gateway = create_default_gateway(allowed_workspace_roots=[tmp_path])
    stale_hash = "sha256:" + ("0" * 64)

    result = gateway.execute(
        _request(
            "repo.write_file",
            RiskLevel.L1,
            {
                "workspace_root": str(tmp_path),
                "path": "demo.py",
                "content": "VALUE = 2\n",
                "expected_sha256": stale_hash,
            },
            agent_type="coder",
        )
    )

    assert result.status == "failed"
    assert result.error_code == "file_hash_conflict"
    assert target.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_scaffold_prepares_and_reuses_independent_git_workspace(tmp_path: Path) -> None:
    """Scaffold 必须复制 fixture、创建 baseline commit，并在重试时复用。"""

    source = tmp_path / "fixture"
    source.mkdir()
    (source / "README.md").write_text("# sample\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    gateway = create_default_gateway(
        allowed_workspace_roots=[source, workspace_root],
    )
    arguments = {
        "template_id": "sample-repo-python",
        "source_root": str(source),
        "workspace_root": str(workspace_root),
        "target_directory": "task-001/repo",
    }

    first = gateway.execute(
        _request(
            "scaffold.prepare_workspace",
            RiskLevel.L1,
            arguments,
            agent_type="scaffold",
        )
    )
    second = gateway.execute(
        _request(
            "scaffold.prepare_workspace",
            RiskLevel.L1,
            arguments,
            agent_type="scaffold",
        )
    )

    assert first.status == "succeeded"
    assert first.result_json is not None
    assert first.result_json["reused"] is False
    assert len(first.result_json["baseline_commit"]) == 40
    assert (workspace_root / "task-001" / "repo" / ".git").is_dir()
    assert second.status == "succeeded"
    assert second.result_json is not None
    assert second.result_json["reused"] is True
    assert (
        second.result_json["baseline_commit"]
        == first.result_json["baseline_commit"]
    )

    marker = (
        workspace_root
        / "task-001"
        / "repo"
        / ".git"
        / "cloudhelm-scaffold.json"
    )
    marker.unlink()
    missing_marker = gateway.execute(
        _request(
            "scaffold.prepare_workspace",
            RiskLevel.L1,
            arguments,
            agent_type="scaffold",
        )
    )
    assert missing_marker.status == "failed"
    assert missing_marker.error_code == "scaffold_marker_missing"


def test_pytest_tool_parses_real_junit_semantics(tmp_path: Path, monkeypatch) -> None:
    """pytest 退出码和 JUnit 统计必须共同决定测试结论。"""

    report = tmp_path / ".cloudhelm" / "artifacts" / "junit.xml"
    report.parent.mkdir(parents=True)
    report.write_text(
        '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1" time="0.5"/></testsuites>',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        test_tool,
        "run_process",
        lambda *args, **kwargs: ProcessResult(
            exit_code=1,
            stdout="1 failed, 1 passed, 1 skipped",
            stderr="",
        ),
    )

    result = test_tool.run_pytest(
        PytestToolArguments(workspace_root=str(tmp_path)),
        create_default_gateway(allowed_workspace_roots=[tmp_path]).policy,
    )

    assert result["status"] == "succeeded"
    assert result["result_json"]["passed"] is False
    assert result["result_json"]["passed_count"] == 1
    assert result["result_json"]["failed_count"] == 1
    assert result["result_json"]["skipped_count"] == 1


def test_security_tools_parse_findings_without_treating_exit_one_as_crash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Bandit/pip-audit 的 findings 退出码应成为可审查报告。"""

    (tmp_path / "src").mkdir()
    bandit_payload = {
        "metrics": {},
        "results": [
            {
                "test_id": "B101",
                "test_name": "assert_used",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "filename": str(tmp_path / "src" / "main.py"),
                "line_number": 3,
                "issue_text": "Use of assert detected.",
            }
        ],
    }
    pip_payload = [
        {
            "name": "demo",
            "version": "1.0",
            "vulns": [
                {
                    "id": "PYSEC-DEMO",
                    "aliases": [],
                    "fix_versions": ["1.1"],
                    "description": "demo vulnerability",
                }
            ],
        },
        {
            "name": "local-package",
            "skip_reason": "Dependency not found on PyPI",
        },
    ]
    results = iter(
        [
            ProcessResult(exit_code=1, stdout=json.dumps(bandit_payload), stderr=""),
            ProcessResult(exit_code=1, stdout=json.dumps(pip_payload), stderr=""),
        ]
    )
    monkeypatch.setattr(
        security_tool,
        "run_process",
        lambda *args, **kwargs: next(results),
    )
    policy = create_default_gateway(allowed_workspace_roots=[tmp_path]).policy

    bandit = security_tool.run_bandit(
        SecurityRunBanditArguments(workspace_root=str(tmp_path)),
        policy,
    )
    pip_audit = security_tool.run_pip_audit(
        SecurityRunPipAuditArguments(workspace_root=str(tmp_path)),
        policy,
    )

    assert bandit["status"] == "succeeded"
    assert bandit["result_json"]["findings"][0]["rule_id"] == "B101"
    assert bandit["result_json"]["findings"][0]["path"] == "src/main.py"
    assert pip_audit["status"] == "succeeded"
    assert pip_audit["result_json"]["findings"][0]["id"] == "PYSEC-DEMO"
    assert pip_audit["result_json"]["audited_dependency_count"] == 1
    assert pip_audit["result_json"]["skipped_dependencies"] == [
        {
            "name": "local-package",
            "reason": "Dependency not found on PyPI",
        }
    ]


def test_git_diff_includes_untracked_and_format_patch(tmp_path: Path) -> None:
    """Git 证据必须覆盖新文件，并能在提交后生成 base/head patch。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# demo\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    gateway = create_default_gateway(allowed_workspace_roots=[source, workspace_root])
    scaffold = gateway.execute(
        _request(
            "scaffold.prepare_workspace",
            RiskLevel.L1,
            {
                "template_id": "sample-repo-python",
                "source_root": str(source),
                "workspace_root": str(workspace_root),
                "target_directory": "repo",
            },
            agent_type="scaffold",
        )
    )
    assert scaffold.status == "succeeded"
    repo = workspace_root / "repo"
    branch = gateway.execute(
        _request(
            "git.create_branch",
            RiskLevel.L2,
            {"repo_root": str(repo), "branch_name": "codex/m6-test"},
            agent_type="coder",
        )
    )
    assert branch.status == "succeeded"
    (repo / "src").mkdir()
    (repo / "src" / "feature.py").write_text("VALUE = 42\n", encoding="utf-8")

    diff = gateway.execute(
        _request(
            "git.diff",
            RiskLevel.L0,
            {"repo_root": str(repo), "from_ref": "main"},
            agent_type="coder",
        )
    )
    assert diff.status == "succeeded"
    assert diff.result_json is not None
    assert "src/feature.py" in diff.result_json["changed_files"]
    assert "VALUE = 42" in diff.result_json["patch"]

    commit = gateway.execute(
        _request(
            "git.commit",
            RiskLevel.L2,
            {
                "repo_root": str(repo),
                "message": "feat: 增加 M6 示例功能",
                "paths": ["src/feature.py"],
            },
            agent_type="coder",
        )
    )
    assert commit.status == "succeeded"
    patch = gateway.execute(
        _request(
            "git.format_patch",
            RiskLevel.L0,
            {"repo_root": str(repo), "base_ref": "main", "head_ref": "HEAD"},
            agent_type="coder",
        )
    )
    assert patch.status == "succeeded"
    assert patch.result_json is not None
    assert "src/feature.py" in patch.result_json["changed_files"]
    assert "Subject: [PATCH]" in patch.result_json["patch"]


def test_git_diff_without_untracked_files_returns_empty_list(
    tmp_path: Path,
) -> None:
    """关闭 include_untracked 时不得引用未初始化的内部变量。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# demo\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    gateway = create_default_gateway(
        allowed_workspace_roots=[source, workspace_root]
    )
    assert gateway.execute(
        _request(
            "scaffold.prepare_workspace",
            RiskLevel.L1,
            {
                "template_id": "sample-repo-python",
                "source_root": str(source),
                "workspace_root": str(workspace_root),
                "target_directory": "repo",
            },
            agent_type="scaffold",
        )
    ).status == "succeeded"
    repo = workspace_root / "repo"
    (repo / "untracked.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = gateway.execute(
        _request(
            "git.diff",
            RiskLevel.L0,
            {
                "repo_root": str(repo),
                "include_untracked": False,
            },
            agent_type="coder",
        )
    )

    assert result.status == "succeeded"
    assert result.result_json is not None
    assert result.result_json["untracked_files"] == []
    assert "untracked.py" not in result.result_json["changed_files"]
