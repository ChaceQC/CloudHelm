"""Architect Agent 输入输出 schema。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion, RequirementConstraint


class ArchitectAgentInput(BaseModel):
    """Architect Agent 输入。

    设计必须基于已持久化 RequirementSpec，而不是重新解析用户自然语言。
    """

    task_id: UUID = Field(description="任务 ID。")
    project_id: UUID = Field(description="项目 ID。")
    requirement_spec_id: UUID = Field(description="关联需求规格 ID。")
    title: str = Field(min_length=1, description="任务标题。")
    user_story: str = Field(min_length=1, description="用户故事。")
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1, description="验收标准。")
    constraints: list[RequirementConstraint] = Field(default_factory=list, description="约束条件。")
    task_risk_level: RiskLevel = Field(description="任务初始风险等级。")


class ArchitectAgentOutput(BaseModel):
    """Architect Agent 输出。

    输出映射到 `technical_designs`。OpenAPI / DB schema 是草案，不执行迁移
    或真实工具调用。
    """

    summary: str = Field(min_length=1, description="设计摘要。")
    content_markdown: str = Field(min_length=1, description="ADR / 技术设计正文。")
    openapi_json: dict[str, Any] = Field(description="OpenAPI 草案 JSON。")
    db_schema_json: dict[str, Any] = Field(description="数据库 schema 草案 JSON。")
    mermaid_diagram: str = Field(min_length=1, description="Mermaid 流程或模块图。")
    risk_level: RiskLevel = Field(description="设计阶段最高风险。")
    risks: list[str] = Field(default_factory=list, description="设计风险说明。")
    approval_recommended: bool = Field(default=False, description="是否建议进入人工设计审批。")
