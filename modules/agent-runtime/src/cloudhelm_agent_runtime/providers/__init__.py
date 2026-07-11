"""Agent provider 公共导出。

外部与本地 Provider 会反向读取分层 Instructions。这里对这两个实现使用惰性
导入，避免调用方先导入 `instructions` 时形成
`instructions -> providers package -> provider -> instructions` 循环。
"""

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderError,
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
    StructuredAgentProvider,
)
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.usage import (
    ProviderCallMetadata,
    ProviderRequestUsage,
)
from cloudhelm_agent_runtime.providers.tools import (
    ProviderToolCall,
    ProviderToolDefinition,
    collect_tool_calls,
    tool_result_item,
)

__all__ = [
    "AgentProviderError",
    "AgentProviderRequestError",
    "AgentProviderResponseError",
    "LocalStructuredProvider",
    "MissingProviderConfigurationError",
    "OpenAICompatibleProvider",
    "ProviderCallMetadata",
    "ProviderConversation",
    "ProviderRequestUsage",
    "ProviderToolCall",
    "ProviderToolDefinition",
    "StructuredAgentProvider",
    "collect_tool_calls",
    "tool_result_item",
]


def __getattr__(name: str):
    """按需加载会反向依赖 Instructions 的具体 Provider。"""

    if name == "OpenAICompatibleProvider":
        from cloudhelm_agent_runtime.providers.openai_compatible import (
            OpenAICompatibleProvider,
        )

        return OpenAICompatibleProvider
    if name == "LocalStructuredProvider":
        from cloudhelm_agent_runtime.providers.local_structured import (
            LocalStructuredProvider,
        )

        return LocalStructuredProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
