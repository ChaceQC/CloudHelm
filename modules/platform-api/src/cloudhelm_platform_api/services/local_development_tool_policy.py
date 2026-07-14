"""M6 已审批 execution recipe 到 Provider 工具调用的精确映射。"""

from __future__ import annotations

from typing import Any

from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_workspace_resolver import (
    LocalWorkspaceResolver,
)

ApprovedToolCall = tuple[str, dict[str, Any]]


def scaffold_tool_calls(
    context: LocalDevelopmentContext,
) -> list[ApprovedToolCall]:
    """只允许 Scaffold 使用当前 recipe 和项目默认分支准备 workspace。"""

    return [
        (
            "scaffold.prepare_workspace",
            {
                "template_id": context.recipe.template_id,
                "baseline_branch": context.project.default_branch,
            },
        )
    ]


def coder_tool_calls(
    context: LocalDevelopmentContext,
    workspace: LocalWorkspaceResolver,
) -> list[ApprovedToolCall]:
    """把分支、完整文件写入、验证命令和 diff 固定到已审批 recipe。"""

    branch_name = workspace.branch_name(context.task.id)
    writes = [
        (
            "repo.write_file",
            {
                "path": item.path,
                "content": item.content,
                "mode": "replace",
                "create_parent": item.create_parent,
            },
        )
        for item in context.recipe.planned_changes
    ]
    commands = [
        (
            "sandbox.run_command",
            {
                "cwd": item.cwd,
                "command": item.command,
                "timeout_seconds": item.timeout_seconds,
            },
        )
        for item in context.recipe.coder_verification_commands
    ]
    return [
        ("git.create_branch", {"branch_name": branch_name}),
        *writes,
        *commands,
        (
            "git.diff",
            {
                "paths": [item.path for item in context.recipe.planned_changes],
                "include_untracked": True,
            },
        ),
    ]


def tester_tool_calls(
    context: LocalDevelopmentContext,
) -> list[ApprovedToolCall]:
    """只允许 Tester 执行 recipe 测试命令并读取对应 JUnit 文件。"""

    calls: list[ApprovedToolCall] = []
    for item in context.recipe.test_commands:
        calls.append((item.tool_name, dict(item.arguments)))
        junit_path = item.arguments.get("junit_path")
        if isinstance(junit_path, str) and junit_path:
            calls.append(
                (
                    "repo.read_file",
                    {"path": junit_path, "max_bytes": 262144},
                )
            )
    return calls


def reviewer_tool_calls(diff_paths: list[str]) -> list[ApprovedToolCall]:
    """只允许 Reviewer 读取当前 Coder evidence set 的真实 diff。"""

    return [
        (
            "git.diff",
            {
                "paths": list(diff_paths),
                "max_output_chars": 200000,
            },
        )
    ] if diff_paths else []


def security_tool_calls(
    context: LocalDevelopmentContext,
) -> list[ApprovedToolCall]:
    """只允许 Security 执行 recipe 中声明的领域扫描器和参数。"""

    return [
        (item.tool_name, dict(item.arguments))
        for item in context.recipe.security_commands
    ]
