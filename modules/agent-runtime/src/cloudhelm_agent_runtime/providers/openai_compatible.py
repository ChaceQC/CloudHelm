"""OpenAI 兼容 structured outputs provider。

本实现面向支持 `/v1/chat/completions` 与 `response_format.json_schema`
的兼容服务。M4 默认不要求真实外部模型；当用户显式切换到该 provider
但缺少配置时，调用方会收到明确错误并写入失败事件。
"""

from __future__ import annotations

import json
from typing import Any
from urllib import request

from pydantic import BaseModel, ValidationError

from cloudhelm_agent_runtime.providers.base import MissingProviderConfigurationError, StructuredAgentProvider


class OpenAICompatibleProvider(StructuredAgentProvider):
    """OpenAI 兼容模型 provider。"""

    name = "openai_compatible"

    def __init__(self, api_base: str | None, api_key: str | None, model_name: str | None, timeout_seconds: int = 60) -> None:
        self.api_base = api_base.rstrip("/") if api_base else None
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def generate(self, agent_type: str, payload: BaseModel, output_model: type[BaseModel]) -> dict[str, Any]:
        """调用兼容 Chat Completions 的 JSON Schema 输出接口。"""

        if not self.api_base or not self.api_key or not self.model_name:
            raise MissingProviderConfigurationError(
                "openai_compatible provider requires CLOUDHELM_LLM_API_BASE, CLOUDHELM_LLM_MODEL and CLOUDHELM_LLM_API_KEY"
            )
        schema = output_model.model_json_schema()
        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "你是 CloudHelm M4 Agent，只输出符合 JSON Schema 的结构化 JSON。"},
                {"role": "user", "content": payload.model_dump_json()},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"cloudhelm_{agent_type}_output",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        http_request = request.Request(
            f"{self.api_base}/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
        content = payload_json["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
            return output_model.model_validate(parsed).model_dump(mode="json")
        except (json.JSONDecodeError, KeyError, ValidationError) as exc:
            raise ValueError(f"structured output validation failed: {exc}") from exc
