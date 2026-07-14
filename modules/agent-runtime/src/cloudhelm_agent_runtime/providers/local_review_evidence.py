"""Local Reviewer 对完整、未截断安全投影 diff 的确定性门禁。"""

from __future__ import annotations

from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    LocalToolEvidence,
    result_details,
)
from cloudhelm_agent_runtime.schemas.review_report import ReviewIssue

AUTH_PROFILE_AC_IDS = frozenset(
    {
        "AC-AUTH-001",
        "AC-AUTH-002",
        "AC-AUTH-003",
        "AC-AUTH-004",
        "AC-AUTH-005",
        "AC-PROFILE-001",
        "AC-PROFILE-002",
        "AC-PROFILE-003",
        "AC-SEC-001",
        "AC-OBS-001",
        "AC-TEST-001",
    }
)
AUTH_PROFILE_PATCH_MARKERS = (
    "/auth/register",
    "/auth/login",
    "/profile",
    "hashlib.scrypt",
    "hmac.new",
    "CREATE TABLE IF NOT EXISTS users",
    "test_register_",
    "test_profile_",
)
AUTH_PROFILE_REQUIRED_PATHS = frozenset(
    {
        "src/sample_service/auth.py",
        "src/sample_service/auth_security.py",
        "src/sample_service/user_repository.py",
        "src/sample_service/main.py",
        "tests/test_auth_profile.py",
        "tests/test_auth_hardening.py",
    }
)


def inspect_reviewer_diff(
    data,
    item: LocalToolEvidence,
    *,
    start_index: int,
) -> tuple[bool, list[ReviewIssue]]:
    """校验安全投影完整性、路径一致性和受控 auth/profile 内容。"""

    details = result_details(item)
    patch = details.get("patch")
    issues: list[ReviewIssue] = []
    blocked = False

    def add_issue(
        message: str,
        recommendation: str,
        *,
        evidence_blocked: bool,
    ) -> None:
        nonlocal blocked
        issues.append(
            ReviewIssue(
                id=f"ISSUE-{start_index + len(issues):03d}",
                severity="high",
                message=message,
                recommendation=recommendation,
            )
        )
        blocked = blocked or evidence_blocked

    if not isinstance(patch, str) or not patch.strip():
        add_issue(
            "Reviewer 未获得非空 Git patch。",
            "重新读取当前 evidence set 的完整 git.diff 后再评审。",
            evidence_blocked=True,
        )
        return blocked, issues
    if details.get("patch_truncated") is True or "...<truncated:" in patch:
        add_issue(
            "Reviewer 获得的 Git patch 已截断。",
            "提高受控 diff 上限或缩小已审批路径，确保完整 patch 可审计。",
            evidence_blocked=True,
        )

    expected_changed = {item.path for item in data.changed_files}
    requested_paths = set(data.diff_paths)
    raw_changed = details.get("changed_files")
    reported_changed = (
        {
            str(path)
            for path in raw_changed
            if isinstance(path, str) and path
        }
        if isinstance(raw_changed, list)
        else set()
    )
    raw_paths = details.get("paths")
    reported_paths = (
        {
            str(path)
            for path in raw_paths
            if isinstance(path, str) and path
        }
        if isinstance(raw_paths, list)
        else set()
    )
    if (
        not expected_changed
        or expected_changed != requested_paths
        or expected_changed != reported_changed
        or requested_paths != reported_paths
    ):
        add_issue(
            "Reviewer 的 changed_files、diff_paths 与 git.diff 结果不一致。",
            "使用同一 Coder evidence set 重新生成完整路径集合和 diff。",
            evidence_blocked=True,
        )
    missing_headers = sorted(
        item.path
        for item in data.changed_files
        if not _has_complete_file_patch(patch, item)
    )
    if missing_headers:
        add_issue(
            f"Git patch 缺少文件头：{', '.join(missing_headers)}。",
            "重新读取包含全部 changed files 的完整 patch。",
            evidence_blocked=True,
        )

    criterion_ids = {
        item.id for item in data.acceptance_criteria
    }
    if criterion_ids == AUTH_PROFILE_AC_IDS:
        missing_paths = sorted(
            AUTH_PROFILE_REQUIRED_PATHS - expected_changed
        )
        if missing_paths:
            add_issue(
                "Auth/profile patch 缺少必需文件："
                f"{', '.join(missing_paths)}。",
                "补齐认证、仓储、应用装配和黑盒/白盒测试文件后重新评审。",
                evidence_blocked=False,
            )
        missing_markers = [
            marker
            for marker in AUTH_PROFILE_PATCH_MARKERS
            if marker not in patch
        ]
        if missing_markers:
            add_issue(
                "Auth/profile patch 缺少必需实现或测试标记："
                f"{', '.join(missing_markers)}。",
                "补齐路由、持久化、安全原语和黑盒/白盒测试后重新评审。",
                evidence_blocked=False,
            )
    return blocked, issues


def _has_complete_file_patch(patch: str, changed_file) -> bool:
    """按 created/updated/deleted 语义校验单文件 diff header。"""

    path = changed_file.path
    header = f"diff --git a/{path} b/{path}"
    start = patch.find(header)
    if start < 0:
        return False
    end = patch.find("\ndiff --git ", start + len(header))
    section = patch[start:] if end < 0 else patch[start:end]
    expected_headers = {
        "created": ("--- /dev/null", f"+++ b/{path}"),
        "updated": (f"--- a/{path}", f"+++ b/{path}"),
        "deleted": (f"--- a/{path}", "+++ /dev/null"),
    }[changed_file.operation]
    return all(value in section for value in expected_headers)
