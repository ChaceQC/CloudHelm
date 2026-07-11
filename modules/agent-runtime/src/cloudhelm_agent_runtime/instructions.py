"""CloudHelm 分层 Instructions 读取与 turn context 构造。

Base Instructions 在整个 conversation 内保持稳定；角色、校验修复和 subagent
边界作为 developer ResponseItem 进入当前 turn，既保留审计上下文，也避免因
Requirement/Architect/Planner 角色切换而错误创建新会话。
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.contracts import (
    developer_message_item,
    user_message_item,
)

ROLE_ALLOWED_TOOLS: dict[str, tuple[str, ...]] = {
    "requirement": (
        "requirement.normalize",
        "repo.read_file",
        "repo.search_text",
        "repo.list_files",
    ),
    "architect": (
        "requirement.normalize",
        "design.render_markdown",
        "repo.read_file",
        "repo.search_text",
        "repo.list_files",
    ),
    "planner": (
        "requirement.normalize",
        "design.render_markdown",
        "repo.read_file",
        "repo.search_text",
        "repo.list_files",
    ),
}

ROLE_PROMPT_FILES = {
    "requirement": "requirement.md",
    "architect": "architect.md",
    "planner": "planner.md",
}

ROLE_OUTPUT_CONTRACTS = {
    "requirement": "RequirementAgentOutput",
    "architect": "ArchitectAgentOutput",
    "planner": "PlannerAgentOutput",
}


@lru_cache(maxsize=1)
def base_instructions() -> str:
    """读取跨角色稳定 Base Instructions。"""

    return _read_prompt("base.md")


@lru_cache(maxsize=None)
def role_instructions(agent_type: str) -> str:
    """读取指定角色的完整 Instructions，并附加机器可核对工具列表。"""

    prompt_file = ROLE_PROMPT_FILES.get(agent_type)
    if prompt_file is None:
        raise ValueError(f"missing role instructions for agent type: {agent_type}")
    tools = ROLE_ALLOWED_TOOLS[agent_type]
    tool_context = {
        "agent_type": agent_type,
        "allowed_tools": list(tools),
        "conversation_rule": "reuse_root_unless_explicit_subagent_spawn",
        "output_contract": ROLE_OUTPUT_CONTRACTS[agent_type],
        "output_transport_schema": "cloudhelm_agent_output_v1",
        "side_effect_policy": "tool_gateway_and_approval_only",
    }
    return (
        f"{_read_prompt(prompt_file)}\n\n"
        "<role_contract>\n"
        f"{json.dumps(tool_context, ensure_ascii=False, sort_keys=True)}\n"
        "</role_contract>"
    )


def allowed_tools_for(agent_type: str) -> tuple[str, ...]:
    """返回角色唯一权威的工具 allowlist。"""

    try:
        return ROLE_ALLOWED_TOOLS[agent_type]
    except KeyError as exc:
        raise ValueError(f"missing tool policy for agent type: {agent_type}") from exc


def build_turn_input_items(
    agent_type: str,
    payload: BaseModel,
    *,
    validation_feedback: str | None = None,
    explicit_cache_breakpoint: bool = False,
) -> list[dict[str, Any]]:
    """构造一个 Agent turn 的 role、业务输入和可选修复指令。

    `explicit_cache_breakpoint` 必须由 Provider capability/config 显式启用。
    不支持该 Responses 扩展字段的兼容端点可能返回网关错误，因此不能默认发送。
    """

    envelope = {
        "agent_type": agent_type,
        "input_contract": payload.__class__.__name__,
        "output_contract": ROLE_OUTPUT_CONTRACTS[agent_type],
        "conversation_scope": "task_root",
        "input": payload.model_dump(mode="json"),
    }
    items = [
        developer_message_item(role_instructions(agent_type)),
        user_message_item(
            json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            cache_breakpoint=explicit_cache_breakpoint,
        ),
    ]
    if validation_feedback:
        items.append(validation_repair_item(agent_type, validation_feedback))
    return items


def validation_repair_item(
    agent_type: str,
    validation_feedback: str,
) -> dict[str, Any]:
    """构造只在当前格式修复尝试出现的精确 developer 指令。"""

    payload = {
        "error_source": "local_pydantic_validation",
        "target_output_contract": ROLE_OUTPUT_CONTRACTS[agent_type],
        "output_transport_schema": "cloudhelm_agent_output_v1",
        "repair_scope": [
            "字段名与 required 字段",
            "JSON 类型、enum、pattern、minLength 与 minItems",
            "ID 前缀、连续编号、唯一性与跨字段引用",
            "依赖图闭合和无环",
            "当前角色固定状态与风险一致性",
        ],
        "must_preserve": [
            "当前 Task、Project 与 artifact identity",
            "已经正确的业务语义和已批准约束",
            "真实输入、工具结果与审批事实",
        ],
        "forbidden": [
            "输出当前角色 contract 未声明的其他角色字段",
            "删除需求以绕过校验",
            "添加 schema 未声明字段",
            "输出 JSON Patch、diff、Markdown 或解释",
            "伪造工具、测试、审批、缓存或部署结果",
        ],
        "instruction": "重新输出目标 contract 的完整 JSON object。",
        "validation_error": validation_feedback[:4000],
    }
    text = (
        "<validation_repair>\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "</validation_repair>"
    )
    return developer_message_item(text)


def subagent_instructions(
    *,
    parent_conversation_id: str,
    agent_role: str,
    depth: int,
    fork_context: bool,
) -> dict[str, Any]:
    """构造 child conversation 创建时的完整边界指令。"""

    metadata = {
        "source_type": "subagent",
        "parent_conversation_id": parent_conversation_id,
        "agent_role": agent_role,
        "depth": depth,
        "fork_context": fork_context,
        "fork_mode": "full_history" if fork_context else "fresh",
        "history_merge_policy": "final_notification_only",
        "permission_inheritance": "none",
    }
    return developer_message_item(
        f"{_read_prompt('subagent.md')}\n\n"
        "<subagent_contract>\n"
        f"{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}\n"
        "</subagent_contract>"
    )


def subagent_task_item(
    *,
    objective: str,
    expected_result: str,
) -> dict[str, Any]:
    """构造 child conversation 唯一显式子目标。"""

    payload = {
        "objective": objective,
        "expected_result": expected_result,
        "scope_rule": "只处理 objective，不接管父 Task 全部职责。",
        "completion_rule": (
            "满足当前 Role output contract 后返回结构化结果和简洁摘要；"
            "缺少上下文、权限或审批时返回 blocked/风险证据。"
        ),
    }
    return user_message_item(
        "<subagent_task>\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "</subagent_task>"
    )


@lru_cache(maxsize=None)
def _read_prompt(filename: str) -> str:
    """以 UTF-8 读取包内版本化 Prompt。"""

    resource = files("cloudhelm_agent_runtime.prompts").joinpath(filename)
    return resource.read_text(encoding="utf-8").strip()
