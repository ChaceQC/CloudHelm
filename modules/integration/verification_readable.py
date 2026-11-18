"""Generate a reviewer-facing report from authoritative verification facts."""

from dataclasses import dataclass
from urllib.parse import quote

from packages.contracts.p2.verification import VerificationView

from .reference_report_words import REFERENCE_CHECK_WORDS


_RESULT = {"passed": "通过", "failed": "未通过", "unknown": "证据不完整，无法判定通过", "not_run": "未执行"}
_PHASE = {
    "baseline": "页面、便签操作和输入校验",
    "seed": "为重启验证写入便签",
    "verify-persisted": "检查后端重启后数据是否保留",
    "not-ready": "检查数据库不可用时的服务响应",
    "other": "其他检查",
}
_INTEGRITY = {
    "verification_execution_unavailable": "未能执行指定的验收阶段。",
    "verification_phase_unfinished": "有验收阶段缺少执行完成记录。",
    "verification_duplicate_phase": "同一轮包含重复的阶段记录。",
    "verification_asset_bundle_changed": "阶段执行使用的验收资产与本轮登记不符。",
    "reference_assets_before_execution_invalid": "执行前无法核对独立验收资产。",
    "reference_assets_after_execution_changed": "执行前后的独立验收资产不一致。",
    "reference_assets_after_execution_invalid": "执行后无法核对独立验收资产。",
    "reference_execution_timeout": "独立检查运行超时，没有取得完整结果。",
    "reference_execution_unavailable": "无法启动或读取独立检查的执行结果。",
    "reference_output_too_large": "独立检查输出超出记录上限，无法确认完整性。",
    "reference_output_binding_mismatch": "输出的验收方法、需求修订或执行阶段与本轮不符。",
    "reference_case_counts_mismatch": "工具报告的检查数量与实际结果列表不一致。",
    "reference_duplicate_check_id": "检查结果中出现重复记录。",
    "reference_check_set_incomplete": "输出的检查集合与本阶段要求不一致。",
    "reference_passed_flag_mismatch": "工具声明的通过状态与逐项结果不一致。",
    "reference_exit_code_mismatch": "工具的退出状态与逐项结果不一致。",
    "reference_output_invalid": "独立检查输出无法解析为规定的结果。",
}


@dataclass(frozen=True, slots=True)
class VerificationPublication:
    view: VerificationView
    summary: str
    markdown: str


def verification_report_path(view: VerificationView) -> str:
    report = view.report
    return f"/api/tasks/{quote(report.task_id, safe='')}/verifications/{quote(report.report_id, safe='')}"


def verification_headline(view: VerificationView) -> str:
    report = view.report
    if view.applicability == "needs_review":
        usage = "当前输入需要复核，这份报告不能作为当前的通过依据。"
    elif view.usable:
        usage = "这份报告可用于当前候选的审查。"
    else:
        usage = "这份报告未满足通过条件。"
    return (f"验收结论：{_RESULT[report.evidence.result]}。"
            f"应检查 {len(report.expected_check_ids)} 项，{len(report.passed_check_ids)} 项通过，"
            f"{len(report.failed_check_ids)} 项失败，{len(report.missing_check_ids)} 项缺少结果。{usage}")


def publish_verification(view: VerificationView) -> VerificationPublication:
    report = view.report
    summary = verification_headline(view)
    method = report.evidence.method_ref
    reference_method = method.object_id == "reference-http-r1" and method.revision in {
        "reference-http-r1.1", f"reference-http-r1.1-{report.asset_bundle_digest[7:]}",
    }
    words = REFERENCE_CHECK_WORDS if reference_method else {}
    expected = set(report.expected_check_ids)
    passed, failed = set(report.passed_check_ids), set(report.failed_check_ids)
    groups: dict[str, list[tuple[str, str, str]]] = {phase: [] for phase in _PHASE}
    ordered_checks = [item for item in words if item in expected]
    ordered_checks.extend(item for item in report.expected_check_ids if item not in words)
    for check_id in ordered_checks:
        phase, label, criterion = words.get(check_id, (
            "other", f"检查 {len(groups['other']) + 1}", "此验收修订未登记中文说明，具体断言见原始报告。",
        ))
        status = "失败" if check_id in failed else "通过" if check_id in passed else "缺少结果"
        groups[phase].append((label, status, criterion))

    lines = ["# 正式验收报告", "", f"**{summary}**", ""]
    if reference_method:
        lines.extend(("独立验收的范围包括页面资源、便签操作及输入校验、后端重启与数据库故障。"
                      "页面检查的通过标准是资源可访问，不涉及浏览器内的交互。", ""))
    if report.integrity_errors:
        problems = dict.fromkeys(_INTEGRITY.get(code, "有未识别的完整性问题，见原始报告。")
                                 for code in report.integrity_errors)
        lines.extend(("## 影响判定的问题", "", *(f"- {problem}" for problem in problems), ""))
    lines.extend(("## 各阶段的检查结果", ""))
    finished = {phase.phase for phase in report.phases}
    for phase, rows in groups.items():
        if not rows:
            continue
        count = sum(status == "通过" for _, status, _ in rows)
        lines.extend((f"### {_PHASE[phase]}（{count}/{len(rows)} 项通过）", ""))
        if phase != "other" and phase not in finished:
            lines.extend(("原报告没有本阶段的执行完成记录。", ""))
        lines.extend(("| 检查场景 | 实际判定 | 通过标准 |", "|---|---|---|"))
        lines.extend(f"| {label} | {status} | {criterion} |" for label, status, criterion in rows)
        lines.append("")
    lines.extend(("## 核对原始证据", "",
                  f"- 报告：`{quote(report.report_id, safe='')}`",
                  f"- 候选提交：`{quote(report.source_ref.revision, safe='')}`",
                  f"- 报告时间（UTC）：{report.evidence.observed_at.isoformat()}",
                  f"- [原始验收报告与证据引用]({verification_report_path(view)})", "",
                  "逐项判定来自原报告。项目审查与批准有单独的记录。"))
    return VerificationPublication(view=view, summary=summary, markdown="\n".join(lines) + "\n")
