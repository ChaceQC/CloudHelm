"""本地 M4 provider 支持范围与受控 recipe 识别。"""

from cloudhelm_agent_runtime.providers.local_requirement_rules import contains_any
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput
from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentInput

AUTH_PROFILE_RECIPE_ID = "demo-issue-001-auth-profile-v1"
AUTH_PROFILE_SOURCE_REF = "demo-issues/001-auth-profile.md"
AUTH_PROFILE_AC_IDS = (
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
)
AUTH_PROFILE_RECIPE_MARKER = (
    f"<!-- cloudhelm-local-recipe:{AUTH_PROFILE_RECIPE_ID} -->"
)


def is_sample_auth_design(data: ArchitectAgentInput) -> bool:
    """只在来源和完整 AC 集合均匹配受控 demo issue 时启用领域设计。"""

    source_refs = {
        item.value
        for item in data.constraints
        if item.type == "source_ref"
    }
    criterion_ids = tuple(item.id for item in data.acceptance_criteria)
    return (
        AUTH_PROFILE_SOURCE_REF in source_refs
        and criterion_ids == AUTH_PROFILE_AC_IDS
    )


def is_sample_auth_plan(data: PlannerAgentInput) -> bool:
    """通过 Architect 写入的稳定 marker 识别受控 demo plan。"""

    return AUTH_PROFILE_RECIPE_MARKER in data.design_summary


def is_cloudhelm_internal_design(data: ArchitectAgentInput) -> bool:
    """只识别显式标注为 CloudHelm M4 核验的本地任务。"""

    text = "\n".join(
        [
            data.title,
            data.user_story,
            *[item.description for item in data.acceptance_criteria],
            *[item.value for item in data.constraints],
        ]
    )
    return contains_any(text, ["cloudhelm m4", "云舵 m4"])


def is_cloudhelm_internal_plan(data: PlannerAgentInput) -> bool:
    """只识别由显式 CloudHelm M4 核验设计生成的计划。"""

    return contains_any(
        f"{data.title}\n{data.design_summary}",
        ["cloudhelm m4", "云舵 m4"],
    )
