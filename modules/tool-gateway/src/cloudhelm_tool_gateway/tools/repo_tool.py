"""Repo Tool 本地文件工具。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.schemas.repo import (
    RepoListFilesArguments,
    RepoReadFileArguments,
    RepoSearchTextArguments,
    RepoWriteFileArguments,
)


def _relative(root: Path, path: Path) -> str:
    """返回 POSIX 风格相对路径，便于跨平台 API 展示。"""

    return path.relative_to(root).as_posix()


def _sha256_file(path: Path) -> str:
    """按块计算文件 hash，避免一次性加载大文件。"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def read_file(args: RepoReadFileArguments, policy: ToolPolicy) -> dict:
    """读取 workspace 内文本文件并返回截断内容。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    path = policy.resolve_workspace_path(root, args.path)
    if not path.is_file():
        raise PolicyError("path_not_file", "repo.read_file 只能读取文件。")
    size = path.stat().st_size
    with path.open("rb") as file:
        data = file.read(args.max_bytes + 1)
    truncated = len(data) > args.max_bytes
    content = data[: args.max_bytes].decode("utf-8", errors="replace")
    return {
        "summary": f"已读取 {_relative(root, path)}，大小 {size} bytes。",
        "result_json": {
            "path": _relative(root, path),
            "content": content,
            "truncated": truncated,
            "size_bytes": size,
            "sha256": _sha256_file(path),
        },
    }


def write_file(args: RepoWriteFileArguments, policy: ToolPolicy) -> dict:
    """以 replace 方式写入文本文件，并支持内容 hash 乐观锁。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    target = policy.resolve_workspace_path(root, args.path, allow_missing=True)
    parent = target.parent
    if not parent.exists():
        if not args.create_parent:
            raise PolicyError("parent_not_found", "父目录不存在；未启用 create_parent。")
        policy.create_workspace_directories(root, parent)
    if target.exists() and not target.is_file():
        raise PolicyError("path_not_file", "repo.write_file 只能写入文件。")
    if args.expected_sha256 == "missing" and target.exists():
        raise PolicyError("file_hash_conflict", "目标文件已存在，不满足 expected_sha256=missing。")
    if args.expected_sha256 and args.expected_sha256 != "missing":
        if not target.exists() or _sha256_file(target) != args.expected_sha256:
            raise PolicyError("file_hash_conflict", "目标文件 hash 已变化，拒绝覆盖。")
    with target.open("w", encoding="utf-8", newline="\n") as file:
        file.write(args.content)
    sha256 = _sha256_file(target)
    return {
        "summary": f"已写入 {_relative(root, target)}。",
        "result_json": {
            "path": _relative(root, target),
            "bytes_written": len(args.content.encode("utf-8")),
            "sha256": sha256,
        },
    }


def list_files(args: RepoListFilesArguments, policy: ToolPolicy) -> dict:
    """列出 workspace 内文件。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    base = policy.resolve_workspace_path(root, args.path)
    if not base.is_dir():
        raise PolicyError("path_not_directory", "repo.list_files 的 path 必须是目录。")
    items = []
    for candidate in sorted(base.glob(args.glob)):
        try:
            checked = policy.resolve_workspace_path(root, candidate)
        except PolicyError:
            continue
        if checked.is_dir() and not args.include_dirs:
            continue
        if len(items) >= args.limit:
            break
        items.append(
            {
                "path": _relative(root, checked),
                "is_dir": checked.is_dir(),
                "size_bytes": None if checked.is_dir() else checked.stat().st_size,
            }
        )
    return {"summary": f"已列出 {len(items)} 个路径。", "result_json": {"items": items, "truncated": len(items) >= args.limit}}


def search_text(args: RepoSearchTextArguments, policy: ToolPolicy) -> dict:
    """按普通字符串搜索 workspace 内文本。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    needle = args.pattern if args.case_sensitive else args.pattern.lower()
    matches = []
    for candidate in sorted(root.glob(args.glob)):
        if len(matches) >= args.max_matches:
            break
        try:
            path = policy.resolve_workspace_path(root, candidate)
        except PolicyError:
            continue
        if not path.is_file() or path.stat().st_size > args.max_file_bytes:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        haystack = text if args.case_sensitive else text.lower()
        for line_number, line in enumerate(text.splitlines(), start=1):
            source = line if args.case_sensitive else line.lower()
            if needle in source:
                matches.append({"path": _relative(root, path), "line": line_number, "snippet": line[:240]})
                if len(matches) >= args.max_matches:
                    break
    return {"summary": f"搜索完成，命中 {len(matches)} 处。", "result_json": {"matches": matches}}
