"""跨角色稳定且兼容的 Responses Structured Output schema。

Prompt Caching 会把 Structured Output schema 放在消息前缀之前参与匹配，因此
Requirement、Architect、Planner 不能分别发送不同 schema。部分 OpenAI 兼容
端点又会在根级 `anyOf` / 大量 `$ref` schema 上返回网关错误。

本模块发送一份扁平、稳定、覆盖全部当前角色字段的传输 schema；当前 turn
最终仍必须通过对应 `output_model` 的严格 Pydantic 校验。这样既保持跨角色
缓存前缀，也不会把宽松传输层当成业务校验层。
"""

from __future__ import annotations

from copy import deepcopy

from pydantic import BaseModel

from cloudhelm_agent_runtime.schemas import (
    ArchitectAgentOutput,
    CoderAgentOutput,
    PlannerAgentOutput,
    RequirementAgentOutput,
    ReviewerAgentOutput,
    ScaffoldAgentOutput,
    SecurityAgentOutput,
    TesterAgentOutput,
)

STABLE_OUTPUT_SCHEMA_NAME = "cloudhelm_agent_output_v1"
SUPPORTED_OUTPUT_MODELS: tuple[type[BaseModel], ...] = (
    RequirementAgentOutput,
    ArchitectAgentOutput,
    PlannerAgentOutput,
    ScaffoldAgentOutput,
    CoderAgentOutput,
    TesterAgentOutput,
    ReviewerAgentOutput,
    SecurityAgentOutput,
)

_STABLE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "risk_level": {
            "type": "string",
            "enum": ["L0", "L1", "L2", "L3", "L4"],
        },
        "raw_input": {"type": "string"},
        "user_story": {"type": "string"},
        "constraints": {"type": "array"},
        "acceptance_criteria": {"type": "array"},
        "content_markdown": {"type": "string"},
        "openapi_json": {
            "type": "object",
            "additionalProperties": True,
        },
        "db_schema_json": {
            "type": "object",
            "additionalProperties": True,
        },
        "mermaid_diagram": {"type": "string"},
        "risks": {"type": "array"},
        "approval_recommended": {"type": "boolean"},
        "steps": {"type": "array"},
        "status": {"type": "string"},
        "task_id": {"type": "string", "format": "uuid"},
        "development_plan_id": {"type": "string", "format": "uuid"},
        "step_id": {"type": "string"},
        "step_ids": {"type": "array"},
        "workspace_key": {"type": ["string", "null"]},
        "baseline_branch": {"type": ["string", "null"]},
        "baseline_commit": {"type": ["string", "null"]},
        "baseline_files": {"type": "array"},
        "branch_name": {"type": ["string", "null"]},
        "diff_paths": {"type": "array"},
        "changed_files": {"type": "array"},
        "verification": {"type": "array"},
        "tests_added": {"type": "array"},
        "commands": {"type": "array"},
        "passed_count": {"type": ["integer", "null"]},
        "failed_count": {"type": ["integer", "null"]},
        "skipped_count": {"type": ["integer", "null"]},
        "tool_calls": {"type": "array"},
        "artifacts": {"type": "array"},
        "blockers": {"type": "array"},
        "failure_reasons": {"type": "array"},
        "verdict": {"type": "string"},
        "acceptance_results": {"type": "array"},
        "issues": {"type": "array"},
        "proceed_to_security": {"type": "boolean"},
        "scanners": {"type": "array"},
        "findings": {"type": "array"},
        "remaining_risks": {"type": "array"},
        "blocking": {"type": "boolean"},
    },
    "required": ["summary", "risk_level"],
    "additionalProperties": False,
}


def stable_output_schema(output_model: type[BaseModel]) -> dict:
    """返回跨当前所有普通角色一致的扁平 JSON Schema。

    参数:
        output_model: 当前 turn 最终必须通过校验的 Pydantic 输出类型。

    异常:
        ValueError: 当前输出类型尚未加入稳定协议。禁止静默回退到角色专属
        schema，否则会从请求起始位置破坏同一 Task 的缓存前缀。
    """

    if output_model not in SUPPORTED_OUTPUT_MODELS:
        raise ValueError(
            f"unsupported stable agent output model: {output_model.__name__}"
        )
    return deepcopy(_STABLE_OUTPUT_SCHEMA)
