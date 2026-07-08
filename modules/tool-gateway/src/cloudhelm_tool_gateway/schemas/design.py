"""Design Tool 参数模型。"""

from pydantic import BaseModel, Field


class DesignRenderMarkdownArguments(BaseModel):
    """将结构化设计要点渲染成 Markdown 草案。"""

    title: str = Field(min_length=1, max_length=120)
    decisions: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
