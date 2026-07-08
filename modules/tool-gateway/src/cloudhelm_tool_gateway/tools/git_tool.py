"""Git Tool 本地受控 Git 操作。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from cloudhelm_tool_gateway.audit import truncate_text
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.schemas.git import GitCommitArguments, GitCreateBranchArguments, GitDiffArguments, GitStatusArguments

BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")


def _run_git(repo: Path, args: list[str], max_chars: int = 12000) -> tuple[int, str, str]:
    """执行 git 命令并返回退出码和截断输出。"""

    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    return completed.returncode, truncate_text(completed.stdout, max_chars) or "", truncate_text(completed.stderr, max_chars) or ""


def _repo_root(repo_root: str, policy: ToolPolicy) -> Path:
    """校验 repo_root 是受控 Git 仓库根目录。"""

    root = policy.resolve_workspace_root(repo_root)
    code, stdout, stderr = _run_git(root, ["rev-parse", "--show-toplevel"])
    if code != 0:
        raise PolicyError("not_git_repo", f"repo_root 不是 Git 仓库：{stderr.strip()}")
    top = Path(stdout.strip()).resolve(strict=True)
    if top != root:
        raise PolicyError("repo_root_mismatch", "Git Tool 只能操作仓库根目录。")
    return root


def _validate_branch_name(branch_name: str) -> None:
    """校验分支名，阻止 rev 注入和 Git 保留后缀。"""

    if not BRANCH_PATTERN.match(branch_name) or ".." in branch_name or branch_name.endswith(("/", ".lock")):
        raise PolicyError("invalid_branch_name", "分支名包含 Git 不安全字符或保留格式。")


def status(args: GitStatusArguments, policy: ToolPolicy) -> dict:
    """读取 git status。"""

    repo = _repo_root(args.repo_root, policy)
    git_args = ["status", "--short", "--branch"] if args.porcelain else ["status"]
    code, stdout, stderr = _run_git(repo, git_args)
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_status_failed",
        "summary": "已读取 Git 状态。" if code == 0 else "读取 Git 状态失败。",
        "stdout_summary": stdout,
        "stderr_summary": stderr,
        "result_json": {"exit_code": code, "porcelain": args.porcelain},
    }


def diff(args: GitDiffArguments, policy: ToolPolicy) -> dict:
    """读取 git diff 和 diff stat。"""

    repo = _repo_root(args.repo_root, policy)
    paths = []
    for path in args.paths:
        checked = policy.resolve_workspace_path(repo, path, allow_missing=True)
        paths.append(checked.relative_to(repo).as_posix())
    separator = ["--", *paths] if paths else []
    stat_code, stat_out, stat_err = _run_git(repo, ["diff", "--stat", *separator], args.max_output_chars)
    patch_code, patch_out, patch_err = _run_git(repo, ["diff", f"--unified={args.context_lines}", *separator], args.max_output_chars)
    code = stat_code or patch_code
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_diff_failed",
        "summary": "已读取 Git diff。" if code == 0 else "读取 Git diff 失败。",
        "stdout_summary": patch_out,
        "stderr_summary": stat_err or patch_err,
        "result_json": {"exit_code": code, "stat": stat_out, "paths": paths},
    }


def create_branch(args: GitCreateBranchArguments, policy: ToolPolicy) -> dict:
    """创建并切换本地分支。"""

    repo = _repo_root(args.repo_root, policy)
    _validate_branch_name(args.branch_name)
    code, stdout, stderr = _run_git(repo, ["switch", "-c", args.branch_name])
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_create_branch_failed",
        "summary": f"已创建并切换到 {args.branch_name}。" if code == 0 else "创建分支失败。",
        "stdout_summary": stdout,
        "stderr_summary": stderr,
        "result_json": {"branch_name": args.branch_name, "exit_code": code},
    }


def commit(args: GitCommitArguments, policy: ToolPolicy) -> dict:
    """提交显式文件列表。"""

    repo = _repo_root(args.repo_root, policy)
    paths = []
    for path in args.paths:
        checked = policy.resolve_workspace_path(repo, path, allow_missing=True)
        paths.append(checked.relative_to(repo).as_posix())
    add_code, _, add_err = _run_git(repo, ["add", "--", *paths])
    if add_code != 0:
        return {"status": "failed", "error_code": "git_add_failed", "summary": "git add 失败。", "stderr_summary": add_err}
    check_code, _, _ = _run_git(repo, ["diff", "--cached", "--quiet", "--", *paths])
    if check_code == 0:
        return {"status": "failed", "error_code": "git_no_staged_changes", "summary": "指定文件没有可提交变更。"}
    commit_code, commit_out, commit_err = _run_git(repo, ["commit", "-m", args.message])
    hash_code, hash_out, _ = _run_git(repo, ["rev-parse", "HEAD"])
    commit_hash = hash_out.strip() if hash_code == 0 else None
    return {
        "status": "succeeded" if commit_code == 0 else "failed",
        "error_code": None if commit_code == 0 else "git_commit_failed",
        "summary": f"已创建本地提交 {commit_hash}。" if commit_code == 0 else "本地提交失败。",
        "stdout_summary": commit_out,
        "stderr_summary": commit_err,
        "result_json": {"paths": paths, "commit_hash": commit_hash, "exit_code": commit_code},
    }
