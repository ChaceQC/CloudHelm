"""pytest 领域工具。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from time import perf_counter

from cloudhelm_tool_gateway.audit import truncate_text
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.process_runner import run_process
from cloudhelm_tool_gateway.schemas.test_run import TestRunPytestArguments


def run_pytest(args: TestRunPytestArguments, policy: ToolPolicy) -> dict:
    """执行真实 pytest，解析 JUnit，并区分测试失败与基础设施失败。"""

    root = policy.resolve_workspace_root(args.workspace_root)
    cwd = policy.resolve_workspace_path(root, args.cwd)
    if not cwd.is_dir():
        raise PolicyError("cwd_not_directory", "test.run_pytest 的 cwd 必须是目录。")
    junit_path = policy.resolve_workspace_path(root, args.junit_path, allow_missing=True)
    if not junit_path.parent.exists():
        policy.create_workspace_directories(root, junit_path.parent)

    command = policy.validate_command(
        [
            "uv",
            "run",
            "pytest",
            *args.pytest_args,
            f"--junitxml={junit_path}",
        ],
        allowed_programs={"uv"},
    )
    timeout_seconds = policy.validate_timeout(args.timeout_seconds, maximum=300)
    started = perf_counter()
    result = run_process(
        command,
        cwd=cwd,
        env=policy.build_subprocess_env(),
        timeout_seconds=timeout_seconds,
        policy=policy,
        max_output_chars=args.max_output_chars,
    )
    duration_ms = int((perf_counter() - started) * 1000)
    common = {
        "stdout_summary": truncate_text(result.stdout, args.max_output_chars),
        "stderr_summary": truncate_text(result.stderr, args.max_output_chars),
    }
    if result.command_not_found:
        return {
            "status": "failed",
            "error_code": "pytest_command_not_found",
            "summary": "当前环境未找到 uv，pytest 未执行。",
            "result_json": {"duration_ms": duration_ms},
            **common,
        }
    if result.timed_out:
        return {
            "status": "failed",
            "error_code": "pytest_timeout",
            "summary": f"pytest 超过 {timeout_seconds}s 已终止。",
            "result_json": {"duration_ms": duration_ms, "timeout_seconds": timeout_seconds},
            **common,
        }
    if result.exit_code not in {0, 1, 5}:
        return {
            "status": "failed",
            "error_code": "pytest_execution_failed",
            "summary": f"pytest 基础设施退出码 {result.exit_code}。",
            "result_json": {"exit_code": result.exit_code, "duration_ms": duration_ms},
            **common,
        }
    try:
        counts = _parse_junit(junit_path)
    except (OSError, ET.ParseError, ValueError) as exc:
        return {
            "status": "failed",
            "error_code": "junit_parse_failed",
            "summary": f"pytest 已执行，但 JUnit 解析失败：{type(exc).__name__}。",
            "result_json": {"exit_code": result.exit_code, "duration_ms": duration_ms},
            **common,
        }
    passed = result.exit_code == 0 and counts["failures"] == 0 and counts["errors"] == 0
    outcome = "passed" if passed else ("no_tests" if result.exit_code == 5 else "failed")
    return {
        "status": "succeeded",
        "summary": (
            f"pytest 通过：{counts['passed']} passed。"
            if passed
            else f"pytest 未通过：{counts['failures']} failures，{counts['errors']} errors。"
        ),
        "result_json": {
            "command": ["uv", "run", "pytest", *args.pytest_args],
            "exit_code": result.exit_code,
            "outcome": outcome,
            "passed": passed,
            "tests": counts["tests"],
            "passed_count": counts["passed"],
            "failed_count": counts["failures"] + counts["errors"],
            "failure_count": counts["failures"],
            "error_count": counts["errors"],
            "skipped_count": counts["skipped"],
            "duration_seconds": counts["time"],
            "duration_ms": duration_ms,
            "junit_path": junit_path.relative_to(root).as_posix(),
        },
        **common,
    }


def _parse_junit(path: Path) -> dict[str, int | float]:
    """解析 pytest JUnit 根节点或聚合 testsuite。"""

    if not path.is_file():
        raise ValueError("JUnit file is missing")
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("JUnit contains no testsuite")
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    duration = sum(float(suite.attrib.get("time", 0.0)) for suite in suites)
    passed = max(0, tests - failures - errors - skipped)
    return {
        "tests": tests,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "time": duration,
    }
