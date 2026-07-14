"""OpenAI 兼容 Provider 的重试与结构化输出辅助。"""

import json
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderRequestError,
    AgentProviderResponseError,
)

T = TypeVar("T")


def run_with_retries(
    operation: Callable[[], T],
    *,
    max_attempts: int,
    retry_backoff_seconds: float,
    sleep: Callable[[float], None],
) -> T:
    """对瞬时请求错误和无效结构化响应执行有界指数退避。"""

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except AgentProviderRequestError as exc:
            if not exc.retryable or attempt == max_attempts:
                raise
            retry_after_seconds = exc.retry_after_seconds or 0
        except AgentProviderResponseError:
            if attempt == max_attempts:
                raise
            retry_after_seconds = 0
        delay_seconds = max(
            retry_backoff_seconds * (2 ** (attempt - 1)),
            retry_after_seconds,
        )
        if delay_seconds > 0:
            sleep(delay_seconds)
    raise RuntimeError("unreachable provider retry state")


def parse_structured_output(
    content: str,
    output_model: type[BaseModel],
) -> dict[str, Any]:
    """解析并用调用方指定的 Pydantic 模型再次校验。"""

    try:
        parsed = json.loads(content)
        return output_model.model_validate(parsed).model_dump(mode="json")
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AgentProviderResponseError(
            f"structured output validation failed: {exc}"
        ) from exc
