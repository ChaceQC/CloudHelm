"""Local Tester 的 JUnit testcase 到 Acceptance Criteria 映射。"""

from __future__ import annotations

from collections import defaultdict
from xml.etree import ElementTree

from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    LocalToolEvidence,
    result_details,
)
from cloudhelm_agent_runtime.schemas.test_report import AcceptanceTestResult


def map_acceptance_results(
    data,
    junit_evidence: list[LocalToolEvidence],
    evidence_refs: list[str],
) -> tuple[list[AcceptanceTestResult], list[str]]:
    """按 recipe 声明的稳定 testcase 名逐 AC 判定，而非整批一键通过。"""

    testcase_statuses: dict[str, list[str]] = defaultdict(list)
    errors: list[str] = []
    for item in junit_evidence:
        details = result_details(item)
        if details.get("truncated") is True:
            errors.append("JUnit XML 已截断，不能作为完整 AC 证据。")
            continue
        content = details.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append("JUnit 工具结果缺少非空 XML content。")
            continue
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            errors.append(f"JUnit XML 解析失败：{exc}.")
            continue
        _collect_testcases(root, testcase_statuses)

    results = [
        _map_one_acceptance(
            mapping,
            testcase_statuses,
            evidence_refs,
            force_not_covered=bool(errors),
        )
        for mapping in data.acceptance_evidence
    ]
    return results, errors


def not_covered_results(data, notes: str) -> list[AcceptanceTestResult]:
    """基础设施阻断时保留 recipe notes，但不宣称任何 AC 已通过。"""

    return [
        AcceptanceTestResult(
            criterion_id=item.criterion_id,
            status="not_covered",
            evidence_refs=[],
            notes=f"{item.notes}；{notes}",
        )
        for item in data.acceptance_evidence
    ]


def _collect_testcases(
    root: ElementTree.Element,
    statuses: dict[str, list[str]],
) -> None:
    """收集函数名、参数化基名和 classname-qualified 名称。"""

    for testcase in root.iter("testcase"):
        name = testcase.get("name")
        if not name:
            continue
        status = _testcase_status(testcase)
        base_name = name.split("[", 1)[0]
        keys = {name, base_name}
        classname = testcase.get("classname")
        if classname:
            keys.add(f"{classname}.{name}")
            keys.add(f"{classname}.{base_name}")
        for key in keys:
            statuses[key].append(status)


def _testcase_status(testcase: ElementTree.Element) -> str:
    """把 JUnit testcase 子节点归一为 passed/failed/skipped。"""

    if testcase.find("failure") is not None or testcase.find("error") is not None:
        return "failed"
    if testcase.find("skipped") is not None:
        return "skipped"
    return "passed"


def _map_one_acceptance(
    mapping,
    statuses: dict[str, list[str]],
    evidence_refs: list[str],
    *,
    force_not_covered: bool,
) -> AcceptanceTestResult:
    """要求映射中的每个 testcase 都存在且通过。"""

    missing: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    for testcase_name in mapping.testcase_names:
        observed = statuses.get(testcase_name, [])
        if not observed:
            missing.append(testcase_name)
        elif "failed" in observed:
            failed.append(testcase_name)
        elif "skipped" in observed:
            skipped.append(testcase_name)

    if force_not_covered or missing or skipped:
        status = "not_covered"
    elif failed:
        status = "failed"
    else:
        status = "passed"
    details = []
    if missing:
        details.append(f"缺少 testcase：{', '.join(missing)}")
    if skipped:
        details.append(f"跳过 testcase：{', '.join(skipped)}")
    if failed:
        details.append(f"失败 testcase：{', '.join(failed)}")
    if force_not_covered:
        details.append("JUnit 证据不完整，不能确认 testcase 覆盖")
    if not details:
        details.append(
            f"已核验 testcase：{', '.join(mapping.testcase_names)}"
        )
    return AcceptanceTestResult(
        criterion_id=mapping.criterion_id,
        status=status,
        evidence_refs=evidence_refs if status != "not_covered" else [],
        notes=f"{mapping.notes}；{'；'.join(details)}。",
    )
