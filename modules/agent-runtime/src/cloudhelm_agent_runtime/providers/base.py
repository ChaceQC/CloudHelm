"""Agent provider 抽象与稳定错误类型。

Provider 层只负责把已校验输入转换为结构化输出，不写业务表、不推进状态机，
也不绕过 Tool Gateway 执行副作用。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.contracts import ProviderConversation

if TYPE_CHECKING:
    from cloudhelm_agent_runtime.providers.exchange import PendingProviderTurn, ProviderExchangeResult
    from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition


class AgentProviderError(RuntimeError):
    """Provider 运行失败，可由调用方写入 AgentRun 错误字段。"""

    code = "agent_provider_error"


class MissingProviderConfigurationError(AgentProviderError):
    """缺少外部模型配置。"""

    code = "missing_agent_provider_config"


class UnsupportedLocalRecipeError(AgentProviderError):
    """本地规则 provider 不支持当前需求语义。"""

    code = "unsupported_local_recipe"


class AgentProviderRequestError(AgentProviderError):
    """外部模型 HTTP 请求失败。

    `retryable` 由 provider 按 HTTP 状态或网络异常分类，供运行时重试和
    Orchestrator 决定暂停还是进入失败终态。
    """

    code = "agent_provider_request_failed"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class AgentProviderResponseError(AgentProviderError):
    """外部模型响应或结构化内容无效，可通过重新生成修复。"""

    code = "agent_provider_response_invalid"
    retryable = True


class StructuredAgentProvider(ABC):
    """结构化 Agent provider 协议。"""

    name: str
    model_name: str | None
    last_call_metadata = None

    @abstractmethod
    def generate(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
        *,
        conversation: ProviderConversation | None = None,
    ) -> dict[str, Any]:
        """根据 Agent 类型和输入生成可由 `output_model` 校验的 JSON。"""


class ToolCapableStructuredAgentProvider(StructuredAgentProvider):
    """支持 Responses 工具循环的结构化 Provider。

    单次 `exchange` 只与模型交换 ResponseItem，不执行 Tool Gateway，也不修改
    已持久化 conversation。调用方负责执行工具并把结果追加到
    `PendingProviderTurn`，最终由通用 runner 一次性提交逻辑 turn。
    """

    @abstractmethod
    def exchange(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
        *,
        conversation: ProviderConversation,
        pending_turn: "PendingProviderTurn",
        tools: tuple["ProviderToolDefinition", ...] = (),
    ) -> "ProviderExchangeResult":
        """执行一次可返回工具调用或最终 JSON 的模型交换。"""
