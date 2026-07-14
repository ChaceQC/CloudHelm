"""受控子进程执行器。

统一处理 UTF-8、超时、进程树清理和命令不存在，供 Sandbox、测试、安全与
Scaffold 工具复用。调用方仍需在执行前完成 workspace、命令和环境策略校验。
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cloudhelm_tool_gateway.policies import ToolPolicy


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """一次受控命令的完整结果。"""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    command_not_found: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False


def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    policy: ToolPolicy,
    max_output_chars: int | None = None,
) -> ProcessResult:
    """用临时文件有界读取输出，并在超时时终止整个进程树。"""

    limit = max_output_chars or policy.max_output_chars
    with (
        tempfile.TemporaryFile(mode="w+b") as stdout_file,
        tempfile.TemporaryFile(mode="w+b") as stderr_file,
    ):
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                **policy.subprocess_group_options(),
            )
        except FileNotFoundError as exc:
            return ProcessResult(
                exit_code=None,
                stdout="",
                stderr=str(exc),
                command_not_found=True,
            )
        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            policy.terminate_process_tree(process)
            process.wait()
        stdout, stdout_truncated = _read_bounded(
            stdout_file,
            limit,
        )
        stderr, stderr_truncated = _read_bounded(
            stderr_file,
            limit,
        )
    if timed_out:
        return ProcessResult(
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
    return ProcessResult(
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _read_bounded(file, max_chars: int) -> tuple[str, bool]:
    """只把临时输出文件前 max_chars 个字符读入内存。"""

    file.seek(0, 2)
    total_bytes = file.tell()
    file.seek(0)
    raw = file.read(max_chars * 4 + 4)
    decoded = raw.decode("utf-8", errors="replace")
    truncated = total_bytes > len(raw) or len(decoded) > max_chars
    return decoded[:max_chars], truncated
