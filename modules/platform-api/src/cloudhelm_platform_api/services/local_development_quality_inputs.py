"""Reviewer/Security 的同 cycle 输入构造。"""

from cloudhelm_agent_runtime.schemas.agent_io import (
    PlannedToolCommand,
    RiskLevel,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion
from cloudhelm_agent_runtime.schemas.review_report import (
    AcceptanceReview,
    ReviewerAgentInput,
)
from cloudhelm_agent_runtime.schemas.security_report import SecurityAgentInput
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentOutput

from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_evidence import (
    ImplementationEvidence,
)


def build_reviewer_input(
    context: LocalDevelopmentContext,
    implementation: ImplementationEvidence,
    test_output: TesterAgentOutput,
    evidence_refs: list[str],
) -> ReviewerAgentInput:
    """把已审批需求、真实 diff 与测试证据映射为 Reviewer 输入。"""

    return ReviewerAgentInput(
        task_id=context.task.id,
        project_id=context.task.project_id,
        development_plan_id=context.plan.id,
        title=context.task.title,
        acceptance_criteria=[
            AcceptanceCriterion.model_validate(item)
            for item in context.requirement.acceptance_criteria_json
        ],
        acceptance_evidence=[
            AcceptanceReview(
                criterion_id=item.criterion_id,
                status=(
                    "satisfied"
                    if test_output.status == "passed"
                    else "missing"
                ),
                evidence_refs=evidence_refs,
                notes=item.notes,
            )
            for item in context.recipe.acceptance_evidence
        ],
        changed_files=implementation.output.changed_files,
        diff_paths=implementation.output.diff_paths,
        test_report=test_output,
        known_issues=[],
        execution_recipe_sha256=context.recipe_sha256,
        risk_level=RiskLevel(context.task.risk_level),
    )


def build_security_input(
    context: LocalDevelopmentContext,
    implementation: ImplementationEvidence,
) -> SecurityAgentInput:
    """把同 cycle changed files 与受控扫描 recipe 构造成 Security 输入。"""

    return SecurityAgentInput(
        task_id=context.task.id,
        project_id=context.task.project_id,
        development_plan_id=context.plan.id,
        title=context.task.title,
        changed_files=implementation.output.changed_files,
        scan_commands=[
            PlannedToolCommand(
                tool_name=item.tool_name,
                arguments=item.arguments,
                command=display_security_command(
                    item.tool_name,
                    item.arguments,
                ),
                purpose=item.purpose,
            )
            for item in context.recipe.security_commands
        ],
        accepted_risks=[],
        execution_recipe_sha256=context.recipe_sha256,
        risk_level=RiskLevel(context.task.risk_level),
    )


def display_security_command(
    tool_name: str,
    arguments: dict,
) -> list[str]:
    """把安全领域工具还原为控制台可读且无 shell 的命令数组。"""

    if tool_name == "security.run_bandit":
        return [
            "uv",
            "run",
            "bandit",
            "-r",
            str(arguments.get("path", "src")),
            "-f",
            "json",
            "-q",
        ]
    if tool_name == "security.run_pip_audit":
        return [
            "uv",
            "run",
            "pip-audit",
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ]
    raise ServiceError(
        "m6_security_tool_invalid",
        f"Security recipe 不允许工具：{tool_name}。",
        409,
    )
