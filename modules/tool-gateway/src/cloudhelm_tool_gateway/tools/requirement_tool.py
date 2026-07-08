"""Requirement Tool 结构化需求辅助工具。"""

from __future__ import annotations

from cloudhelm_tool_gateway.policies import ToolPolicy
from cloudhelm_tool_gateway.schemas.requirement import RequirementNormalizeArguments


def normalize(args: RequirementNormalizeArguments, policy: ToolPolicy) -> dict:  # noqa: ARG001 - 保持工具 handler 统一签名。
    """根据输入生成结构化需求草案。"""

    first_line = next((line.strip() for line in args.raw_input.splitlines() if line.strip()), args.raw_input.strip())
    criteria = args.acceptance_criteria or [f"能够验证需求：{first_line[:80]}"]
    return {
        "summary": "已整理需求输入。",
        "result_json": {
            "user_story": first_line[:300],
            "constraints": args.constraints,
            "acceptance_criteria": criteria,
        },
    }
