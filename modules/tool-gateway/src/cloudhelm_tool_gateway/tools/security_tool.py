"""本地 Python 安全扫描工具。"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from cloudhelm_tool_gateway.audit import truncate_text
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.process_runner import ProcessResult, run_process
from cloudhelm_tool_gateway.schemas.security import (
    SecurityRunBanditArguments,
    SecurityRunPipAuditArguments,
)


def run_bandit(args: SecurityRunBanditArguments, policy: ToolPolicy) -> dict:
    """执行 Bandit JSON 扫描；退出码 1 代表发现问题而非基础设施失败。"""

    root, cwd, scan_path = _resolve_scan_paths(
        args.workspace_root,
        args.cwd,
        args.path,
        policy,
    )
    command = policy.validate_command(
        ["uv", "run", "bandit", "-r", str(scan_path), "-f", "json", "-q"],
        allowed_programs={"uv"},
    )
    result, duration_ms = _execute(
        command,
        cwd,
        args.timeout_seconds,
        args.max_output_chars,
        policy,
    )
    failure = _execution_failure(result, "bandit", duration_ms, args.max_output_chars)
    if failure is not None:
        return failure
    if result.exit_code not in {0, 1}:
        return _nonzero_failure("bandit", result, duration_ms, args.max_output_chars)
    try:
        payload = json.loads(result.stdout or "{}")
        raw_findings = payload.get("results", [])
        if not isinstance(raw_findings, list):
            raise ValueError("results must be an array")
    except (json.JSONDecodeError, ValueError) as exc:
        return _parse_failure("bandit", result, duration_ms, args.max_output_chars, exc)
    findings = [
        {
            "rule_id": item.get("test_id"),
            "test_name": item.get("test_name"),
            "severity": str(item.get("issue_severity") or "UNKNOWN").lower(),
            "confidence": str(item.get("issue_confidence") or "UNKNOWN").lower(),
            "path": _safe_relative(root, item.get("filename")),
            "line": item.get("line_number"),
            "message": item.get("issue_text"),
        }
        for item in raw_findings
        if isinstance(item, dict)
    ]
    return {
        "status": "succeeded",
        "summary": f"Bandit 扫描完成，发现 {len(findings)} 项。",
        "stdout_summary": truncate_text(result.stdout, args.max_output_chars),
        "stderr_summary": truncate_text(result.stderr, args.max_output_chars),
        "result_json": {
            "scanner": "bandit",
            "exit_code": result.exit_code,
            "findings": findings,
            "metrics": payload.get("metrics", {}),
            "duration_ms": duration_ms,
        },
    }


def run_pip_audit(args: SecurityRunPipAuditArguments, policy: ToolPolicy) -> dict:
    """执行 pip-audit JSON 扫描；漏洞发现以结构化结果返回。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    cwd = policy.resolve_workspace_path(root, args.cwd)
    if not cwd.is_dir():
        raise PolicyError("cwd_not_directory", "security.run_pip_audit 的 cwd 必须是目录。")
    command = policy.validate_command(
        ["uv", "run", "pip-audit", "--format", "json", "--progress-spinner", "off"],
        allowed_programs={"uv"},
    )
    result, duration_ms = _execute(
        command,
        cwd,
        args.timeout_seconds,
        args.max_output_chars,
        policy,
    )
    failure = _execution_failure(result, "pip-audit", duration_ms, args.max_output_chars)
    if failure is not None:
        return failure
    if result.exit_code not in {0, 1}:
        return _nonzero_failure("pip-audit", result, duration_ms, args.max_output_chars)
    try:
        payload = json.loads(result.stdout or "[]")
        dependencies = payload.get("dependencies", []) if isinstance(payload, dict) else payload
        if not isinstance(dependencies, list):
            raise ValueError("pip-audit dependencies must be an array")
    except (json.JSONDecodeError, ValueError) as exc:
        return _parse_failure("pip-audit", result, duration_ms, args.max_output_chars, exc)
    findings: list[dict[str, Any]] = []
    skipped_dependencies: list[dict[str, str]] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        skip_reason = dependency.get("skip_reason")
        if isinstance(skip_reason, str) and skip_reason:
            skipped_dependencies.append(
                {
                    "name": str(dependency.get("name") or "unknown"),
                    "reason": skip_reason,
                }
            )
            continue
        for vulnerability in dependency.get("vulns", []):
            if not isinstance(vulnerability, dict):
                continue
            findings.append(
                {
                    "dependency": dependency.get("name"),
                    "version": dependency.get("version"),
                    "id": vulnerability.get("id"),
                    "aliases": vulnerability.get("aliases", []),
                    "fix_versions": vulnerability.get("fix_versions", []),
                    "description": vulnerability.get("description"),
                }
            )
    return {
        "status": "succeeded",
        "summary": (
            f"pip-audit 扫描完成，发现 {len(findings)} 个漏洞记录，"
            f"跳过 {len(skipped_dependencies)} 个依赖。"
        ),
        "stdout_summary": truncate_text(result.stdout, args.max_output_chars),
        "stderr_summary": truncate_text(result.stderr, args.max_output_chars),
        "result_json": {
            "scanner": "pip-audit",
            "exit_code": result.exit_code,
            "findings": findings,
            "dependency_count": len(dependencies),
            "audited_dependency_count": (
                len(dependencies) - len(skipped_dependencies)
            ),
            "skipped_dependencies": skipped_dependencies,
            "duration_ms": duration_ms,
        },
    }


def _resolve_scan_paths(
    workspace_root: str,
    cwd_value: str,
    path_value: str,
    policy: ToolPolicy,
) -> tuple[Path, Path, Path]:
    """解析安全扫描 cwd 与目标路径。"""

    root = policy.resolve_workspace_root(workspace_root)
    cwd = policy.resolve_workspace_path(root, cwd_value)
    scan_path = policy.resolve_workspace_path(root, path_value)
    if not cwd.is_dir() or not scan_path.exists():
        raise PolicyError("security_scan_path_invalid", "安全扫描 cwd 或 path 无效。")
    return root, cwd, scan_path


def _execute(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
    policy: ToolPolicy,
) -> tuple[ProcessResult, int]:
    """执行安全命令并返回持续时间。"""

    timeout = policy.validate_timeout(timeout_seconds, maximum=300)
    started = perf_counter()
    result = run_process(
        command,
        cwd=cwd,
        env=policy.build_subprocess_env(),
        timeout_seconds=timeout,
        policy=policy,
        max_output_chars=max_output_chars,
    )
    return result, int((perf_counter() - started) * 1000)


def _execution_failure(
    result: ProcessResult,
    scanner: str,
    duration_ms: int,
    max_output_chars: int,
) -> dict | None:
    """映射命令缺失与超时。"""

    if result.command_not_found:
        return {
            "status": "failed",
            "error_code": "security_command_not_found",
            "summary": f"{scanner} 扫描命令不可用。",
            "stderr_summary": truncate_text(result.stderr, max_output_chars),
            "result_json": {"scanner": scanner, "duration_ms": duration_ms},
        }
    if result.timed_out:
        return {
            "status": "failed",
            "error_code": "security_scan_timeout",
            "summary": f"{scanner} 扫描超时。",
            "stdout_summary": truncate_text(result.stdout, max_output_chars),
            "stderr_summary": truncate_text(result.stderr, max_output_chars),
            "result_json": {"scanner": scanner, "duration_ms": duration_ms},
        }
    return None


def _nonzero_failure(
    scanner: str,
    result: ProcessResult,
    duration_ms: int,
    max_output_chars: int,
) -> dict:
    """映射扫描器非预期退出码。"""

    return {
        "status": "failed",
        "error_code": "security_scan_failed",
        "summary": f"{scanner} 扫描退出码 {result.exit_code}。",
        "stdout_summary": truncate_text(result.stdout, max_output_chars),
        "stderr_summary": truncate_text(result.stderr, max_output_chars),
        "result_json": {
            "scanner": scanner,
            "exit_code": result.exit_code,
            "duration_ms": duration_ms,
        },
    }


def _parse_failure(
    scanner: str,
    result: ProcessResult,
    duration_ms: int,
    max_output_chars: int,
    exc: Exception,
) -> dict:
    """映射安全报告 JSON 损坏。"""

    return {
        "status": "failed",
        "error_code": "security_report_parse_failed",
        "summary": f"{scanner} 输出无法解析：{type(exc).__name__}。",
        "stdout_summary": truncate_text(result.stdout, max_output_chars),
        "stderr_summary": truncate_text(result.stderr, max_output_chars),
        "result_json": {
            "scanner": scanner,
            "exit_code": result.exit_code,
            "duration_ms": duration_ms,
        },
    }


def _safe_relative(root: Path, value: object) -> str | None:
    """把扫描器文件路径投影为 workspace 相对路径。"""

    if not isinstance(value, str):
        return None
    try:
        return Path(value).resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return Path(value).name
