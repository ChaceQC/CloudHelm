"""Scaffold/Coder 输入构造与公开事件记录。"""

from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.implementation import (
    CoderAgentInput,
    CoderAgentOutput,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion
from cloudhelm_agent_runtime.schemas.scaffold import ScaffoldAgentInput

from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_step_support import (
    RunningLocalAgentStep,
)
from cloudhelm_platform_api.services.local_workspace_resolver import (
    LocalWorkspaceResolver,
)
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)


def build_scaffold_input(
    context: LocalDevelopmentContext,
    workspace: LocalWorkspaceResolver,
) -> ScaffoldAgentInput:
    """构造只包含服务端绑定 workspace 引用的 Scaffold 输入。"""

    return ScaffoldAgentInput(
        task_id=context.task.id,
        project_id=context.task.project_id,
        development_plan_id=context.plan.id,
        step_id=context.recipe.step_ids[0],
        title=context.task.title,
        workspace_ref=workspace.workspace_ref(context.task.id),
        template_id=context.recipe.template_id,
        baseline_branch=context.project.default_branch,
        execution_recipe_sha256=context.recipe_sha256,
        risk_level=RiskLevel(context.task.risk_level),
    )


def build_coder_input(
    context: LocalDevelopmentContext,
    workspace: LocalWorkspaceResolver,
    prior_feedback: list[str],
) -> CoderAgentInput:
    """构造已审批 recipe、完整 AC 与固定分支的 Coder 输入。"""

    return CoderAgentInput(
        task_id=context.task.id,
        project_id=context.task.project_id,
        development_plan_id=context.plan.id,
        step_ids=context.recipe.step_ids,
        title=context.task.title,
        implementation_goal=context.recipe.implementation_goal,
        branch_name=workspace.branch_name(context.task.id),
        execution_recipe_sha256=context.recipe_sha256,
        acceptance_criteria=[
            AcceptanceCriterion.model_validate(item)
            for item in context.requirement.acceptance_criteria_json
        ],
        planned_changes=context.recipe.planned_changes,
        verification_commands=context.recipe.coder_verification_commands,
        prior_feedback=prior_feedback,
        risk_level=RiskLevel(context.task.risk_level),
    )


def collect_coder_feedback(
    session,
    context: LocalDevelopmentContext,
) -> list[str]:
    """收集当前计划最近测试、评审和安全回退原因，供 Coder 下一轮修正。"""

    runs = AgentRunRepository(session)
    feedback: list[str] = []
    for workflow_step in ("run_tester", "run_reviewer", "run_security"):
        run = runs.latest_by_workflow_step(context.task.id, workflow_step)
        if run is None:
            continue
        output = run.structured_output_json or {}
        if output.get("development_plan_id") != str(context.plan.id):
            continue
        if run.status == "failed" and run.error_message:
            feedback.append(f"{workflow_step}: {run.error_message}")
            continue
        feedback.extend(_output_feedback(workflow_step, output))
    return list(dict.fromkeys(item[:1000] for item in feedback if item))[:20]


def _output_feedback(workflow_step: str, output: dict) -> list[str]:
    """把不同质量 Agent 的结构化失败字段投影为稳定文本。"""

    values: list[str] = []
    for field_name in ("failure_reasons", "remaining_risks", "blockers"):
        items = output.get(field_name)
        if isinstance(items, list):
            values.extend(
                f"{workflow_step}: {item}"
                for item in items
                if isinstance(item, str) and item.strip()
            )
    for field_name in ("issues", "findings"):
        items = output.get(field_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            message = item.get("message") or item.get("recommendation")
            if isinstance(message, str) and message.strip():
                values.append(f"{workflow_step}: {message}")
    return values


def record_coder_events(
    events: EventService,
    context: LocalDevelopmentContext,
    step: RunningLocalAgentStep,
    output: CoderAgentOutput,
    artifacts: list,
) -> None:
    """记录 branch 与非空 patch 事件，不携带源码正文。"""

    branch_call = next(
        (
            item
            for item in step.executor.tool_calls
            if item.tool_name == "git.create_branch"
        ),
        None,
    )
    if branch_call is not None and branch_call.status.value == "succeeded":
        events.record(
            "BranchCreated",
            "agent",
            str(step.run.id),
            {
                "branch_name": output.branch_name,
                "tool_call_id": str(branch_call.id),
            },
            context.task.id,
        )
    diff_artifact = next(
        (
            item
            for item in artifacts
            if item.artifact_type == "diff_patch"
        ),
        None,
    )
    if diff_artifact is not None:
        events.record(
            "CodePatchGenerated",
            "agent",
            str(step.run.id),
            {
                "artifact_id": str(diff_artifact.id),
                "changed_files": output.diff_paths,
            },
            context.task.id,
        )
