"""工具型 Agent 的单次交换与同一逻辑 turn 管理。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from cloudhelm_agent_runtime.instructions import (
    build_turn_input_items,
    validation_repair_item,
)
from cloudhelm_agent_runtime.providers.base import (
    AgentProviderError,
    AgentProviderResponseError,
    ToolCapableStructuredAgentProvider,
)
from cloudhelm_agent_runtime.providers.contracts import (
    ProviderConversation,
    normalize_response_item,
    validate_conversation_items,
)
from cloudhelm_agent_runtime.providers.prompt_cache import combine_call_metadata
from cloudhelm_agent_runtime.providers.tools import (
    ProviderToolCall,
    ProviderToolDefinition,
    ProviderToolExecutionResult,
    collect_tool_calls,
    execution_result_item,
    stable_tool_definitions,
)
from cloudhelm_agent_runtime.providers.usage import ProviderCallMetadata

ToolExecutor = Callable[[ProviderToolCall], ProviderToolExecutionResult]


class ToolExecutorFatalError(AgentProviderError):
    """工具执行器自身持久化/编排异常，必须中止当前 AgentRun。"""

    code = "tool_executor_fatal"


@dataclass(frozen=True, slots=True)
class ProviderExchangeResult:
    """一次模型交换的完整可重放结果。"""

    response_items: tuple[dict[str, Any], ...]
    output_text: str | None
    tool_calls: tuple[ProviderToolCall, ...]
    metadata: ProviderCallMetadata | None = None
    response_id: str | None = None

    @classmethod
    def from_response(
        cls,
        response_items: list[dict[str, Any]],
        *,
        output_text: str | None,
        metadata: ProviderCallMetadata | None = None,
        response_id: str | None = None,
    ) -> "ProviderExchangeResult":
        """规范化 ResponseItem，并按原始顺序提取工具调用。"""

        normalized = tuple(normalize_response_item(item) for item in response_items)
        calls = tuple(collect_tool_calls(list(normalized)))
        if output_text is None and not calls:
            raise AgentProviderResponseError(
                "provider exchange returned neither tool calls nor final output text"
            )
        return cls(
            response_items=normalized,
            output_text=output_text,
            tool_calls=calls,
            metadata=metadata,
            response_id=response_id,
        )


@dataclass(slots=True)
class PendingProviderTurn:
    """一个尚未提交到 root conversation 的完整逻辑 turn。"""

    agent_type: str
    input_items: list[dict[str, Any]]
    exchange_items: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        agent_type: str,
        payload: BaseModel,
        *,
        explicit_cache_breakpoint: bool = False,
    ) -> "PendingProviderTurn":
        """构造只出现一次的 Role Instructions 与业务输入 envelope。"""

        return cls(
            agent_type=agent_type,
            input_items=build_turn_input_items(
                agent_type,
                payload,
                explicit_cache_breakpoint=explicit_cache_breakpoint,
            ),
        )

    def request_items(self) -> list[dict[str, Any]]:
        """返回当前 turn 已确认输入、工具和模型响应的副本。"""

        return deepcopy([*self.input_items, *self.exchange_items])

    def append_exchange(self, items: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> None:
        """追加一次已接受的模型交换。"""

        normalized = [normalize_response_item(item) for item in items]
        prospective = [*self.input_items, *self.exchange_items, *normalized]
        validate_conversation_items(prospective)
        self.exchange_items.extend(deepcopy(normalized))

    def append_tool_result(
        self,
        call: ProviderToolCall,
        result: ProviderToolExecutionResult,
    ) -> None:
        """追加与模型 call 使用同一 call_id 的真实工具结果。"""

        self.append_exchange([execution_result_item(call, result)])

    def append_validation_repair(self, validation_feedback: str) -> None:
        """只追加本轮格式修复指令，不保存无效最终回答。"""

        self.append_exchange(
            [validation_repair_item(self.agent_type, validation_feedback)]
        )

    def commit(
        self,
        conversation: ProviderConversation,
        *,
        response_id: str | None,
    ) -> None:
        """最终输出通过校验后，一次性增加 conversation turn。"""

        conversation.append_turn(
            self.input_items,
            self.exchange_items,
            response_id=response_id,
        )


def run_tool_capable_turn(
    provider: ToolCapableStructuredAgentProvider,
    agent_type: str,
    payload: BaseModel,
    output_model: type[BaseModel],
    *,
    conversation: ProviderConversation,
    tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
    tool_executor: ToolExecutor | None,
    max_rounds: int = 16,
    max_validation_repairs: int = 2,
    explicit_cache_breakpoint: bool = False,
) -> dict[str, Any]:
    """执行多轮 call/output/final JSON，并只提交一个逻辑 conversation turn。

    Tool Gateway 仍由调用方提供的 `tool_executor` 执行。本函数只维护确定性的
    ResponseItem 顺序、结构化校验、usage 聚合和最终原子 conversation append。
    """

    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")
    if max_validation_repairs < 0:
        raise ValueError("max_validation_repairs cannot be negative")

    stable_tools = stable_tool_definitions(tools)
    pending = PendingProviderTurn.start(
        agent_type,
        payload,
        explicit_cache_breakpoint=explicit_cache_breakpoint,
    )
    completed_metadata: list[ProviderCallMetadata] = []
    validation_repairs = 0
    last_response_id: str | None = None

    for _round in range(max_rounds):
        exchange = provider.exchange(
            agent_type,
            payload,
            output_model,
            conversation=conversation,
            pending_turn=pending,
            tools=stable_tools,
        )
        if exchange.metadata is not None:
            completed_metadata.append(exchange.metadata)
        if exchange.response_id is not None:
            last_response_id = exchange.response_id

        if exchange.tool_calls:
            pending.append_exchange(exchange.response_items)
            if tool_executor is None:
                raise AgentProviderError(
                    "tool-capable agent requested tools but no tool executor was provided"
                )
            for call in exchange.tool_calls:
                try:
                    result = tool_executor(call)
                except ToolExecutorFatalError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 工具边界需回传稳定失败。
                    result = ProviderToolExecutionResult(
                        status="failed",
                        result={
                            "summary": f"工具执行器异常：{type(exc).__name__}",
                        },
                        error_code="tool_executor_error",
                    )
                pending.append_tool_result(call, result)
            continue

        if exchange.output_text is None:
            raise AgentProviderResponseError(
                "provider exchange finished without output text"
            )
        try:
            parsed = output_model.model_validate_json(exchange.output_text)
        except ValidationError as exc:
            if validation_repairs >= max_validation_repairs:
                raise AgentProviderResponseError(
                    f"structured output validation failed: {exc}"
                ) from exc
            validation_repairs += 1
            pending.append_validation_repair(str(exc)[:4000])
            continue

        pending.append_exchange(exchange.response_items)
        pending.commit(conversation, response_id=last_response_id)
        metadata = combine_call_metadata(completed_metadata)
        if metadata is not None:
            metadata = metadata.with_conversation(conversation)
        provider.last_call_metadata = metadata
        return parsed.model_dump(mode="json")

    raise AgentProviderResponseError(
        f"tool-capable agent exceeded {max_rounds} exchange rounds"
    )
