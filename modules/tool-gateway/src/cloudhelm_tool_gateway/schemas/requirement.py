"""Requirement Tool 参数模型。"""

from pydantic import BaseModel, Field


class RequirementNormalizeArguments(BaseModel):
    """将原始需求整理成结构化需求片段。"""

    raw_input: str = Field(min_length=1, max_length=8000)
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
