"""Sandbox Tool 本地命令与产物工具。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter

from cloudhelm_tool_gateway.audit import truncate_text
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.process_runner import run_process
from cloudhelm_tool_gateway.schemas.sandbox import SandboxCollectArtifactArguments, SandboxRunCommandArguments


def run_command(args: SandboxRunCommandArguments, policy: ToolPolicy) -> dict:
    """在本地受控目录执行非交互式命令。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    cwd = policy.resolve_workspace_path(root, args.cwd)
    if not cwd.is_dir():
        raise PolicyError("cwd_not_directory", "sandbox.run_command 的 cwd 必须是目录。")
    command = policy.validate_command(
        args.command,
        allowed_programs={
            "python",
            "python3",
            "uv",
            "node",
            "npm",
            "npm.cmd",
            "npx",
            "npx.cmd",
        },
    )
    timeout_seconds = policy.validate_timeout(args.timeout_seconds)
    env = policy.build_subprocess_env(args.env)
    started = perf_counter()
    completed = run_process(
        command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        policy=policy,
        max_output_chars=args.max_output_chars,
    )
    if completed.command_not_found:
        return {
            "status": "failed",
            "error_code": "command_not_found",
            "summary": f"命令不存在：{command[0]}。",
            "stderr_summary": truncate_text(completed.stderr, args.max_output_chars),
            "result_json": {"duration_ms": int((perf_counter() - started) * 1000)},
        }
    if completed.timed_out:
        return {
            "status": "failed",
            "error_code": "command_timeout",
            "summary": f"命令超过 {timeout_seconds}s 已超时。",
            "stdout_summary": truncate_text(completed.stdout, args.max_output_chars),
            "stderr_summary": truncate_text(completed.stderr, args.max_output_chars),
            "result_json": {
                "timeout_seconds": timeout_seconds,
                "duration_ms": int((perf_counter() - started) * 1000),
                "stdout_truncated": completed.stdout_truncated,
                "stderr_truncated": completed.stderr_truncated,
            },
        }
    status = "succeeded" if completed.exit_code == 0 else "failed"
    return {
        "status": status,
        "error_code": None if status == "succeeded" else "command_failed",
        "summary": f"命令退出码 {completed.exit_code}。",
        "stdout_summary": truncate_text(completed.stdout, args.max_output_chars),
        "stderr_summary": truncate_text(completed.stderr, args.max_output_chars),
        "result_json": {
            "cwd": cwd.relative_to(root).as_posix(),
            "exit_code": completed.exit_code,
            "duration_ms": int((perf_counter() - started) * 1000),
            "stdout_truncated": completed.stdout_truncated,
            "stderr_truncated": completed.stderr_truncated,
        },
    }


def collect_artifact(args: SandboxCollectArtifactArguments, policy: ToolPolicy) -> dict:
    """收集 workspace 内产物元数据，不复制到外部目录。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    path = policy.resolve_workspace_path(root, args.path)
    if not path.is_file():
        raise PolicyError("artifact_not_file", "sandbox.collect_artifact 只能收集文件。")
    size = path.stat().st_size
    if size > args.max_bytes:
        raise PolicyError("artifact_too_large", "artifact 超过 max_bytes 限制。")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "summary": f"已收集产物 {path.relative_to(root).as_posix()}，大小 {size} bytes。",
        "result_json": {"path": path.relative_to(root).as_posix(), "size_bytes": size, "sha256": f"sha256:{digest}"},
    }
