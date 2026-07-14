"""Scaffold Tool：准备独立 sample workspace。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.process_runner import run_process
from cloudhelm_tool_gateway.schemas.scaffold import ScaffoldPrepareWorkspaceArguments

IGNORED_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
}
MARKER_NAME = "cloudhelm-scaffold.json"


def prepare_workspace(args: ScaffoldPrepareWorkspaceArguments, policy: ToolPolicy) -> dict:
    """复制受控 fixture、初始化 Git baseline，并支持相同 Task 幂等恢复。"""

    source = policy.resolve_workspace_root(args.source_root)
    workspace_root = policy.resolve_workspace_root(args.workspace_root)
    target = policy.resolve_workspace_path(
        workspace_root,
        args.target_directory,
        allow_missing=True,
    )
    if target == workspace_root:
        raise PolicyError("scaffold_target_invalid", "Scaffold 目标不能是 workspace 根目录。")

    if target.exists():
        if not target.is_dir():
            raise PolicyError("scaffold_target_not_directory", "Scaffold 目标已存在且不是目录。")
        return _existing_workspace(target, workspace_root, args, policy)

    if not target.parent.exists():
        policy.create_workspace_directories(workspace_root, target.parent)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(*sorted(IGNORED_NAMES)),
    )
    try:
        _git_or_raise(target, ["init", "-b", args.baseline_branch], policy)
        _git_or_raise(target, ["config", "user.name", args.git_user_name], policy)
        _git_or_raise(target, ["config", "user.email", args.git_user_email], policy)
        _git_or_raise(target, ["add", "--all"], policy)
        _git_or_raise(target, ["commit", "-m", "chore: 初始化 sample repo 基线"], policy)
        commit = _git_or_raise(target, ["rev-parse", "HEAD"], policy).strip()
        _write_marker(target, args, commit)
    except Exception:
        resolved_target = target.resolve(strict=False)
        if resolved_target.is_relative_to(workspace_root):
            shutil.rmtree(resolved_target, ignore_errors=True)
        raise

    files = _list_source_files(target)
    return {
        "summary": f"已准备 {args.template_id} 独立 workspace，共 {len(files)} 个基线文件。",
        "result_json": {
            "template_id": args.template_id,
            "workspace_key": target.relative_to(workspace_root).as_posix(),
            "baseline_branch": args.baseline_branch,
            "baseline_commit": commit,
            "files": files,
            "reused": False,
        },
    }


def _existing_workspace(
    target: Path,
    workspace_root: Path,
    args: ScaffoldPrepareWorkspaceArguments,
    policy: ToolPolicy,
) -> dict:
    """验证并返回已存在 workspace，避免重试覆盖真实 Coder 修改。"""

    inside = _git_or_raise(target, ["rev-parse", "--is-inside-work-tree"], policy).strip()
    if inside != "true":
        raise PolicyError("scaffold_target_not_git_repo", "已存在 Scaffold 目录不是 Git workspace。")
    marker = _read_marker(target, args)
    baseline_commit = str(marker["baseline_commit"])
    _git_or_raise(
        target,
        ["cat-file", "-e", f"{baseline_commit}^{{commit}}"],
        policy,
    )
    commit = _git_or_raise(target, ["rev-parse", "HEAD"], policy).strip()
    branch = _git_or_raise(target, ["branch", "--show-current"], policy).strip()
    files = _list_source_files(target)
    return {
        "summary": f"复用已存在的 {args.template_id} workspace。",
        "result_json": {
            "template_id": args.template_id,
            "workspace_key": target.relative_to(workspace_root).as_posix(),
            "baseline_branch": args.baseline_branch,
            "current_branch": branch,
            "baseline_commit": baseline_commit,
            "current_commit": commit,
            "files": files,
            "reused": True,
        },
    }


def _write_marker(
    target: Path,
    args: ScaffoldPrepareWorkspaceArguments,
    baseline_commit: str,
) -> None:
    """在 Git 元数据内写入不参与源码 diff 的 Scaffold 身份标记。"""

    marker = {
        "schema_version": "1.0",
        "template_id": args.template_id,
        "baseline_branch": args.baseline_branch,
        "baseline_commit": baseline_commit,
    }
    (target / ".git" / MARKER_NAME).write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_marker(
    target: Path,
    args: ScaffoldPrepareWorkspaceArguments,
) -> dict:
    """校验已存在 workspace 确由同一 Scaffold 模板和基线创建。"""

    marker_path = target / ".git" / MARKER_NAME
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(
            "scaffold_marker_missing",
            "已存在 Git workspace 缺少有效 CloudHelm Scaffold 标记。",
        ) from exc
    expected = {
        "schema_version": "1.0",
        "template_id": args.template_id,
        "baseline_branch": args.baseline_branch,
    }
    if not isinstance(marker, dict) or any(
        marker.get(key) != value for key, value in expected.items()
    ):
        raise PolicyError(
            "scaffold_marker_mismatch",
            "已存在 workspace 的 Scaffold 模板或基线身份不匹配。",
        )
    baseline_commit = marker.get("baseline_commit")
    if (
        not isinstance(baseline_commit, str)
        or len(baseline_commit) != 40
        or any(char not in "0123456789abcdef" for char in baseline_commit)
    ):
        raise PolicyError(
            "scaffold_marker_invalid",
            "Scaffold 标记缺少有效 baseline commit。",
        )
    return marker


def _git_or_raise(repo: Path, arguments: list[str], policy: ToolPolicy) -> str:
    """执行固定 Git 子命令并把失败映射为策略错误。"""

    command = policy.validate_command(["git", "-C", str(repo), *arguments], allowed_programs={"git"})
    result = run_process(
        command,
        cwd=repo,
        env=policy.build_subprocess_env(),
        timeout_seconds=30,
        policy=policy,
        max_output_chars=policy.max_output_chars,
    )
    if result.command_not_found:
        raise PolicyError("git_not_found", "当前环境未找到 Git。")
    if result.timed_out:
        raise PolicyError("git_timeout", "Scaffold 初始化 Git 超时。")
    if result.exit_code != 0:
        raise PolicyError("git_scaffold_failed", result.stderr.strip() or "Scaffold Git 命令失败。")
    return result.stdout


def _list_source_files(root: Path) -> list[str]:
    """列出 workspace 中非 Git 的基线文件。"""

    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )
