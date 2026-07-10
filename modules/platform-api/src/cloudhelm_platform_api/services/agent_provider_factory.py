"""M4 Agent Provider 构造器。

集中处理 provider 配置选择，避免编排用例服务直接依赖各 provider 的构造细节。
"""

from cloudhelm_agent_runtime.providers import LocalStructuredProvider, OpenAICompatibleProvider, StructuredAgentProvider

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.services.exceptions import ServiceError


class AgentProviderFactory:
    """根据平台配置创建结构化 Agent provider。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(self) -> StructuredAgentProvider:
        """创建当前配置对应的 provider。"""

        if self.settings.agent_provider == "local_structured":
            return LocalStructuredProvider()
        if self.settings.agent_provider == "openai_compatible":
            return OpenAICompatibleProvider(
                api_base=self.settings.llm_api_base,
                api_key=self.settings.llm_api_key,
                model_name=self.settings.llm_model,
                api_mode=self.settings.llm_api_mode,
                reasoning_effort=self.settings.llm_reasoning_effort,
                max_output_tokens=self.settings.llm_max_output_tokens,
                timeout_seconds=self.settings.llm_timeout_seconds,
                max_attempts=self.settings.llm_max_attempts,
                retry_backoff_seconds=self.settings.llm_retry_backoff_seconds,
            )
        raise ServiceError(
            "unsupported_agent_provider",
            f"不支持的 Agent provider：{self.settings.agent_provider}",
            400,
        )
