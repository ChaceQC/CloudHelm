"""Git Tool 内部校验、状态解析和未跟踪文件 diff 辅助。"""

from __future__ import annotations

import re
import subprocess
from difflib import unified_diff
from pathlib import Path

from cloudhelm_tool_gateway.audit import truncate_text
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy

BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")


def run_git(
    repo: Path,
    args: list[str],
    max_chars: int = 12000,
) -> tuple[int, str, str]:
    """执行 Git 命令并返回退出码和截断输出。"""

    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    return (
        completed.returncode,
        truncate_text(completed.stdout, max_chars) or "",
        truncate_text(completed.stderr, max_chars) or "",
    )


def resolve_repo_root(repo_root: str, policy: ToolPolicy) -> Path:
    """校验 repo_root 是受控 Git 仓库根目录。"""

    root = policy.resolve_workspace_root(repo_root)
    code, stdout, stderr = run_git(root, ["rev-parse", "--show-toplevel"])
    if code != 0:
        raise PolicyError("not_git_repo", f"repo_root 不是 Git 仓库：{stderr.strip()}")
    top = Path(stdout.strip()).resolve(strict=True)
    if top != root:
        raise PolicyError("repo_root_mismatch", "Git Tool 只能操作仓库根目录。")
    return root


def validate_branch_name(branch_name: str) -> None:
    """校验分支名，阻止 rev 注入和 Git 保留后缀。"""

    if (
        not BRANCH_PATTERN.match(branch_name)
        or ".." in branch_name
        or branch_name.endswith(("/", ".lock"))
    ):
        raise PolicyError("invalid_branch_name", "分支名包含 Git 不安全字符或保留格式。")


def commit_paths(
    repo: Path,
    requested_paths: list[str],
    policy: ToolPolicy,
) -> list[str]:
    """把提交路径规范化为显式文件列表。"""

    paths: list[str] = []
    for requested_path in requested_paths:
        checked = policy.resolve_workspace_path(
            repo,
            requested_path,
            allow_missing=True,
        )
        relative = checked.relative_to(repo).as_posix()
        if relative in {"", "."} or (checked.exists() and not checked.is_file()):
            raise PolicyError(
                "git_commit_path_not_file",
                "git.commit 只接受显式文件路径，不能提交仓库根目录或目录。",
            )
        if not checked.exists():
            tracked_code, _, _ = run_git(
                repo,
                ["ls-files", "--error-unmatch", "--", relative],
            )
            if tracked_code != 0:
                raise PolicyError(
                    "git_commit_path_not_found",
                    f"提交路径不存在且不是 tracked 文件：{relative}",
                )
        if relative not in paths:
            paths.append(relative)
    return paths


def parse_porcelain(stdout: str) -> dict:
    """把 porcelain v1 状态解析为稳定字段。"""

    branch = None
    staged: list[str] = []
    modified: list[str] = []
    untracked: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...", 1)[0]
            continue
        if len(line) < 3:
            continue
        code, path = line[:2], line[3:]
        if code == "??":
            untracked.append(path)
            continue
        if code[0] not in {" ", "?"}:
            staged.append(path)
        if code[1] not in {" ", "?"}:
            modified.append(path)
    return {
        "branch": branch,
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
        "clean": not (staged or modified or untracked),
    }


def untracked_files(
    repo: Path,
    paths: list[str],
    policy: ToolPolicy,
) -> list[str]:
    """读取并校验未跟踪文件列表。"""

    code, stdout, _ = run_git(
        repo,
        ["ls-files", "--others", "--exclude-standard"],
    )
    if code != 0:
        return []
    requested = set(paths)
    result: list[str] = []
    for raw_path in stdout.splitlines():
        checked = policy.resolve_workspace_path(repo, raw_path)
        relative = checked.relative_to(repo).as_posix()
        if requested and relative not in requested:
            continue
        if checked.is_file():
            result.append(relative)
    return result


def untracked_file_patch(
    repo: Path,
    relative_path: str,
    context_lines: int,
) -> str:
    """为 UTF-8 新文件生成 `/dev/null -> b/path` unified diff。"""

    data = (repo / relative_path).read_bytes()
    if b"\x00" in data:
        return f"Binary files /dev/null and b/{relative_path} differ"
    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        unified_diff(
            [],
            lines,
            fromfile="/dev/null",
            tofile=f"b/{relative_path}",
            n=context_lines,
        )
    )


def append_untracked_stat(repo: Path, stat: str, files: list[str]) -> str:
    """把未跟踪文本文件行数加入可读 stat。"""

    extra = []
    for relative_path in files:
        data = (repo / relative_path).read_bytes()
        lines = data.count(b"\n") + (
            1 if data and not data.endswith(b"\n") else 0
        )
        extra.append(f" {relative_path} | {lines} +")
    return "\n".join(part for part in (stat.rstrip(), *extra) if part)
