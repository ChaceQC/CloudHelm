"""Design Tool 结构化设计辅助工具。"""

from __future__ import annotations

from cloudhelm_tool_gateway.policies import ToolPolicy
from cloudhelm_tool_gateway.schemas.design import DesignRenderMarkdownArguments


def render_markdown(args: DesignRenderMarkdownArguments, policy: ToolPolicy) -> dict:  # noqa: ARG001
    """根据结构化设计字段渲染 Markdown 草案。"""

    sections = [f"# {args.title}", ""]
    for heading, items in (("关键决策", args.decisions), ("接口影响", args.interfaces), ("风险与边界", args.risks)):
        sections.extend([f"## {heading}"])
        if items:
            sections.extend([f"- {item}" for item in items])
        else:
            sections.append("- 暂无。")
        sections.append("")
    markdown = "\n".join(sections).strip() + "\n"
    return {"summary": "已渲染设计 Markdown 草案。", "result_json": {"content_markdown": markdown}}
