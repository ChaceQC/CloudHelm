"""OpenAI 兼容 structured outputs provider。

默认使用 Responses API，并支持通过配置传入 reasoning effort；需要兼容
旧服务时可切换到 Chat Completions。外部输出最终仍由 Pydantic 校验，
不会把未校验文本直接交给 Platform API。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Literal
from urllib import error, request

from pydantic import BaseModel, ValidationError

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderRequestError,
    AgentProviderResponseError,
    MissingProviderConfigurationError,
    StructuredAgentProvider,
)

ApiMode = Literal["responses", "chat_completions"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class OpenAICompatibleProvider(StructuredAgentProvider):
    """OpenAI 兼容模型 provider。"""

    name = "openai_compatible"

    def __init__(
        self,
        api_base: str | None,
        api_key: str | None,
        model_name: str | None,
        *,
        api_mode: ApiMode = "responses",
        reasoning_effort: ReasoningEffort = "max",
        max_output_tokens: int = 32768,
        timeout_seconds: int = 120,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        self.api_base = api_base.rstrip("/") if api_base else None
        self.api_key = api_key
        self.model_name = model_name
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def generate(self, agent_type: str, payload: BaseModel, output_model: type[BaseModel]) -> dict[str, Any]:
        """调用 Responses API 或 Chat Completions 并校验结构化输出。"""

        if not self.api_base or not self.api_key or not self.model_name:
            raise MissingProviderConfigurationError(
                "openai_compatible provider requires CLOUDHELM_LLM_API_BASE, CLOUDHELM_LLM_MODEL and CLOUDHELM_LLM_API_KEY"
            )
        def request_and_validate() -> dict[str, Any]:
            """执行一次模型请求并在同一尝试内校验结构化输出。"""

            if self.api_mode == "responses":
                content = self._generate_responses(agent_type, payload, output_model)
            else:
                content = self._generate_chat_completions(agent_type, payload, output_model)
            return self._parse_output(content, output_model)

        return self._run_with_retries(request_and_validate)

    def _generate_responses(self, agent_type: str, payload: BaseModel, output_model: type[BaseModel]) -> str:
        """调用 Responses API，使用 `reasoning.effort` 控制思考强度。"""

        schema = output_model.model_json_schema()
        body = {
            "model": self.model_name,
            "instructions": "你是 CloudHelm M4 Agent，只输出符合 JSON Schema 的结构化 JSON。",
            "input": payload.model_dump_json(),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": f"cloudhelm_{agent_type}_output",
                    "strict": False,
                    "schema": schema,
                }
            },
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        response_json = self._post_json("/v1/responses", body)
        if response_json.get("status") not in {None, "completed"}:
            details = response_json.get("incomplete_details") or {}
            raise AgentProviderResponseError(f"responses API did not complete: {details}")
        return self._extract_responses_text(response_json)

    def _generate_chat_completions(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
    ) -> str:
        """兼容仍只提供 Chat Completions 的 OpenAI-compatible 服务。"""

        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "你是 CloudHelm M4 Agent，只输出符合 JSON Schema 的结构化 JSON。"},
                {"role": "user", "content": payload.model_dump_json()},
            ],
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": self.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"cloudhelm_{agent_type}_output",
                    "strict": False,
                    "schema": output_model.model_json_schema(),
                },
            },
        }
        response_json = self._post_json("/v1/chat/completions", body)
        try:
            return response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentProviderResponseError("chat completions response is missing message content") from exc

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON 请求，并把网络/HTTP/JSON 错误转换为稳定 provider 错误。"""

        http_request = request.Request(
            self._endpoint(path),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            retryable = exc.code in {408, 409, 429} or exc.code >= 500
            raise AgentProviderRequestError(
                f"model API returned HTTP {exc.code}: {detail}",
                retryable=retryable,
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise AgentProviderRequestError(f"model API request failed: {type(exc).__name__}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgentProviderResponseError("model API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise AgentProviderResponseError("model API response must be a JSON object")
        return parsed

    def _run_with_retries(self, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """对瞬时请求错误和无效结构化响应执行有界指数退避重试。"""

        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except AgentProviderRequestError as exc:
                if not exc.retryable or attempt == self.max_attempts:
                    raise
            except AgentProviderResponseError:
                if attempt == self.max_attempts:
                    raise
            delay_seconds = self.retry_backoff_seconds * (2 ** (attempt - 1))
            if delay_seconds > 0:
                time.sleep(delay_seconds)
        raise RuntimeError("unreachable provider retry state")

    def _endpoint(self, path: str) -> str:
        """兼容 API base 以主机或 `/v1` 结尾的两种常见配置。"""

        if self.api_base is None:
            raise MissingProviderConfigurationError("model API base is missing")
        if self.api_base.endswith("/v1") and path.startswith("/v1/"):
            return f"{self.api_base}{path[3:]}"
        return f"{self.api_base}{path}"

    def _extract_responses_text(self, response_json: dict[str, Any]) -> str:
        """从 Responses API 原始 JSON 中提取首个 `output_text`。"""

        direct = response_json.get("output_text")
        if isinstance(direct, str) and direct:
            return direct
        for item in response_json.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str) and text:
                        return text
        raise AgentProviderResponseError("responses API output does not contain output_text")

    def _parse_output(self, content: str, output_model: type[BaseModel]) -> dict[str, Any]:
        """解析并用调用方指定的 Pydantic 模型再次校验。"""

        try:
            parsed = json.loads(content)
            return output_model.model_validate(parsed).model_dump(mode="json")
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise AgentProviderResponseError(f"structured output validation failed: {exc}") from exc
