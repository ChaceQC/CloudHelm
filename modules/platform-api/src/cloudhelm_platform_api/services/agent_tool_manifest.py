"""M6 Agent 可见的稳定 Tool Gateway 声明。

本模块只把应用级 Tool Gateway 注册表投影为 Responses function tools。
模型可见 schema 会移除 workspace/repo 等服务端绑定参数；真实执行仍由
Tool Gateway 的完整 Pydantic schema、Agent allowlist 和风险策略校验。
"""

from cloudhelm_agent_runtime.providers import ProviderToolDefinition
from cloudhelm_tool_gateway import ToolGateway


def build_provider_tool_manifest(
    gateway: ToolGateway,
) -> tuple[ProviderToolDefinition, ...]:
    """返回跨 Scaffold/Coder/Tester/Reviewer/Security 稳定的工具清单。"""

    return tuple(
        ProviderToolDefinition(
            name=declaration.name,
            description=declaration.description,
            parameters=declaration.provider_parameters_schema(),
            strict=False,
        )
        for declaration in gateway.registry.list_tools()
    )
