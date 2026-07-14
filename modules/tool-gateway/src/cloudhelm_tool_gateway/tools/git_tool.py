"""Git Tool 本地受控 Git 操作。"""

from __future__ import annotations

from cloudhelm_tool_gateway.audit import truncate_text
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.schemas.git import (
    GitCommitArguments,
    GitCreateBranchArguments,
    GitDiffArguments,
    GitFormatPatchArguments,
    GitStatusArguments,
)
from cloudhelm_tool_gateway.tools.git_support import (
    append_untracked_stat,
    commit_paths,
    parse_porcelain,
    resolve_repo_root,
    run_git,
    untracked_file_patch,
    untracked_files as list_untracked_files,
    validate_branch_name,
)


def status(args: GitStatusArguments, policy: ToolPolicy) -> dict:
    """读取 git status。"""

    repo = resolve_repo_root(args.repo_root, policy)
    git_args = ["status", "--porcelain=v1", "--branch"] if args.porcelain else ["status"]
    code, stdout, stderr = run_git(repo, git_args)
    parsed = parse_porcelain(stdout) if code == 0 and args.porcelain else {}
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_status_failed",
        "summary": "已读取 Git 状态。" if code == 0 else "读取 Git 状态失败。",
        "stdout_summary": stdout,
        "stderr_summary": stderr,
        "result_json": {"exit_code": code, "porcelain": args.porcelain, **parsed},
    }


def diff(args: GitDiffArguments, policy: ToolPolicy) -> dict:
    """读取 git diff 和 diff stat。"""

    repo = resolve_repo_root(args.repo_root, policy)
    paths = []
    for path in args.paths:
        checked = policy.resolve_workspace_path(repo, path, allow_missing=True)
        paths.append(checked.relative_to(repo).as_posix())
    if args.to_ref is not None and args.from_ref is None:
        raise PolicyError("git_diff_ref_invalid", "指定 to_ref 时必须同时指定 from_ref。")
    refs = [value for value in (args.from_ref, args.to_ref) if value is not None]
    separator = ["--", *paths] if paths else []
    name_code, name_out, name_err = run_git(
        repo,
        ["diff", "--name-only", *refs, *separator],
        args.max_output_chars,
    )
    stat_code, stat_out, stat_err = run_git(
        repo,
        ["diff", "--stat", *refs, *separator],
        args.max_output_chars,
    )
    patch_code, patch_out, patch_err = run_git(
        repo,
        ["diff", f"--unified={args.context_lines}", *refs, *separator],
        args.max_output_chars,
    )
    changed_files = [line for line in name_out.splitlines() if line.strip()]
    untracked_files: list[str] = []
    untracked_files_for_diff: list[str] = []
    if args.include_untracked and args.to_ref is None:
        untracked_files = untracked_files_for_diff = list_untracked_files(
            repo,
            paths,
            policy,
        )
        for path in untracked_files_for_diff:
            if path not in changed_files:
                changed_files.append(path)
        if untracked_files_for_diff:
            untracked_patch = "\n".join(
                untracked_file_patch(repo, path, args.context_lines)
                for path in untracked_files_for_diff
            )
            patch_out = "\n".join(part for part in (patch_out, untracked_patch) if part)
            stat_out = append_untracked_stat(
                repo,
                stat_out,
                untracked_files_for_diff,
            )
    code = name_code or stat_code or patch_code
    patch = truncate_text(patch_out, args.max_output_chars) or ""
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_diff_failed",
        "summary": "已读取 Git diff。" if code == 0 else "读取 Git diff 失败。",
        "stdout_summary": patch,
        "stderr_summary": name_err or stat_err or patch_err,
        "result_json": {
            "exit_code": code,
            "stat": stat_out,
            "paths": paths,
            "changed_files": changed_files,
            "untracked_files": untracked_files,
            "patch": patch,
            "patch_truncated": len(patch_out) > len(patch),
            "from_ref": args.from_ref,
            "to_ref": args.to_ref,
        },
    }


def create_branch(args: GitCreateBranchArguments, policy: ToolPolicy) -> dict:
    """创建并切换本地分支。"""

    repo = resolve_repo_root(args.repo_root, policy)
    validate_branch_name(args.branch_name)
    _, current_out, _ = run_git(repo, ["branch", "--show-current"])
    current_branch = current_out.strip()
    if current_branch == args.branch_name:
        _, commit_out, _ = run_git(repo, ["rev-parse", "HEAD"])
        return {
            "status": "succeeded",
            "summary": f"已位于分支 {args.branch_name}。",
            "result_json": {
                "branch_name": args.branch_name,
                "base_commit": commit_out.strip(),
                "reused": True,
                "exit_code": 0,
            },
        }
    exists_code, _, _ = run_git(
        repo,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{args.branch_name}"],
    )
    if exists_code == 0:
        return {
            "status": "failed",
            "error_code": "git_branch_exists",
            "summary": f"分支 {args.branch_name} 已存在但当前未位于该分支。",
            "result_json": {"branch_name": args.branch_name},
        }
    _, base_out, _ = run_git(repo, ["rev-parse", "HEAD"])
    code, stdout, stderr = run_git(repo, ["switch", "-c", args.branch_name])
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_create_branch_failed",
        "summary": f"已创建并切换到 {args.branch_name}。" if code == 0 else "创建分支失败。",
        "stdout_summary": stdout,
        "stderr_summary": stderr,
        "result_json": {
            "branch_name": args.branch_name,
            "base_commit": base_out.strip(),
            "reused": False,
            "exit_code": code,
        },
    }


def commit(args: GitCommitArguments, policy: ToolPolicy) -> dict:
    """提交显式文件列表。

    为避免把调用前已经暂存的无关修改混入提交，执行前要求 index 为空；
    git add 或 git commit 失败时会撤销本次新增的暂存状态，但不修改工作区。
    """

    repo = resolve_repo_root(args.repo_root, policy)
    index_code, index_out, index_err = run_git(repo, ["diff", "--cached", "--name-only"])
    if index_code != 0:
        return {"status": "failed", "error_code": "git_index_check_failed", "summary": "检查 Git index 失败。", "stderr_summary": index_err}
    if index_out.strip():
        return {
            "status": "failed",
            "error_code": "git_index_not_clean",
            "summary": "Git index 已包含调用外暂存内容，拒绝创建提交。",
            "result_json": {"staged_paths": index_out.splitlines()},
        }

    paths = commit_paths(repo, args.paths, policy)
    _, base_out, _ = run_git(repo, ["rev-parse", "HEAD"])
    diff_code, diff_stat, diff_err = run_git(repo, ["diff", "--stat", "--", *paths])
    if diff_code != 0:
        return {
            "status": "failed",
            "error_code": "git_diff_failed",
            "summary": "提交前读取 diff stat 失败。",
            "stderr_summary": diff_err,
        }
    add_code, _, add_err = run_git(repo, ["add", "--", *paths])
    if add_code != 0:
        run_git(repo, ["reset", "--quiet", "HEAD", "--", *paths])
        return {"status": "failed", "error_code": "git_add_failed", "summary": "git add 失败。", "stderr_summary": add_err}
    cached_stat_code, cached_stat, cached_stat_err = run_git(
        repo,
        ["diff", "--cached", "--stat", "--", *paths],
    )
    if cached_stat_code != 0:
        run_git(repo, ["reset", "--quiet", "HEAD", "--", *paths])
        return {
            "status": "failed",
            "error_code": "git_diff_failed",
            "summary": "提交前读取 staged diff stat 失败。",
            "stderr_summary": cached_stat_err,
        }
    if cached_stat:
        diff_stat = cached_stat
    check_code, _, _ = run_git(repo, ["diff", "--cached", "--quiet", "--", *paths])
    if check_code == 0:
        _, subject_out, _ = run_git(repo, ["log", "-1", "--format=%s"])
        _, committed_paths_out, _ = run_git(repo, ["show", "--format=", "--name-only", "HEAD"])
        committed_paths = {line for line in committed_paths_out.splitlines() if line}
        if subject_out.strip() == args.message and set(paths) <= committed_paths:
            _, commit_out, _ = run_git(repo, ["rev-parse", "HEAD"])
            return {
                "status": "succeeded",
                "summary": f"复用已有本地提交 {commit_out.strip()}。",
                "result_json": {
                    "paths": paths,
                    "changed_files": paths,
                    "base_commit": None,
                    "commit_hash": commit_out.strip(),
                    "diff_stat": "",
                    "reused": True,
                    "exit_code": 0,
                },
            }
        return {"status": "failed", "error_code": "git_no_staged_changes", "summary": "指定文件没有可提交变更。"}
    commit_code, commit_out, commit_err = run_git(repo, ["commit", "--only", "-m", args.message, "--", *paths])
    if commit_code != 0:
        run_git(repo, ["reset", "--quiet", "HEAD", "--", *paths])
    hash_code, hash_out, _ = run_git(repo, ["rev-parse", "HEAD"])
    commit_hash = hash_out.strip() if hash_code == 0 else None
    return {
        "status": "succeeded" if commit_code == 0 else "failed",
        "error_code": None if commit_code == 0 else "git_commit_failed",
        "summary": f"已创建本地提交 {commit_hash}。" if commit_code == 0 else "本地提交失败。",
        "stdout_summary": commit_out,
        "stderr_summary": commit_err,
        "result_json": {
            "paths": paths,
            "changed_files": paths,
            "base_commit": base_out.strip(),
            "commit_hash": commit_hash,
            "diff_stat": diff_stat,
            "reused": False,
            "exit_code": commit_code,
        },
    }


def format_patch(args: GitFormatPatchArguments, policy: ToolPolicy) -> dict:
    """生成 base/head 的可审计 patch，不创建远端 PR。"""

    repo = resolve_repo_root(args.repo_root, policy)
    for ref in (args.base_ref, args.head_ref):
        code, _, stderr = run_git(repo, ["rev-parse", "--verify", ref])
        if code != 0:
            return {
                "status": "failed",
                "error_code": "git_ref_not_found",
                "summary": f"Git ref 不存在：{ref}。",
                "stderr_summary": stderr,
            }
    patch_code, patch_out, patch_err = run_git(
        repo,
        ["format-patch", "--stdout", f"{args.base_ref}..{args.head_ref}"],
        args.max_output_chars,
    )
    name_code, names_out, names_err = run_git(
        repo,
        ["diff", "--name-only", args.base_ref, args.head_ref],
        50000,
    )
    stat_code, stat_out, stat_err = run_git(
        repo,
        ["diff", "--stat", args.base_ref, args.head_ref],
        50000,
    )
    code = patch_code or name_code or stat_code
    patch = truncate_text(patch_out, args.max_output_chars) or ""
    return {
        "status": "succeeded" if code == 0 else "failed",
        "error_code": None if code == 0 else "git_format_patch_failed",
        "summary": "已生成本地 format-patch。" if code == 0 else "生成 format-patch 失败。",
        "stdout_summary": truncate_text(patch, 50000),
        "stderr_summary": patch_err or names_err or stat_err,
        "result_json": {
            "base_ref": args.base_ref,
            "head_ref": args.head_ref,
            "changed_files": [line for line in names_out.splitlines() if line],
            "stat": stat_out,
            "patch": patch,
            "patch_truncated": len(patch_out) > len(patch),
            "exit_code": code,
        },
    }
