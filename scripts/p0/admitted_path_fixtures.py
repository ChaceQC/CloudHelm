"""Fixed Responses API JSON fixtures; deliberately omit usage fields."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from scripts.p0.model_boundary import MODEL_NAME

OUTPUT_CAP = 64


class RepairAnswer(BaseModel):
    answer: str


class CompactionSummary(BaseModel):
    summary: str


def agent_for_path(client: AsyncOpenAI, path: str) -> Any:
    model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    settings = {
        "max_tokens": OUTPUT_CAP,
        "openai_reasoning_effort": "max",
        "openai_service_tier": "default",
    }
    if path == "validator_repair":
        agent = Agent(model, output_type=RepairAnswer, model_settings=settings, retries=1)
        reject_first = True

        @agent.output_validator
        def reject_one_result(_ctx: Any, output: RepairAnswer) -> RepairAnswer:
            nonlocal reject_first
            if reject_first:
                reject_first = False
                raise ModelRetry("fixed local validator rejection")
            return output

        return agent
    if path == "summary_compaction":
        return (
            Agent(model, output_type=CompactionSummary, model_settings=settings, retries=0),
            Agent(model, model_settings=settings, retries=0),
        )
    return Agent(model, model_settings=settings, retries=0)


class FixtureBytes(httpx.AsyncByteStream):
    def __init__(self, body: bytes, after_read: Callable[[], Any] | None = None) -> None:
        self.body = body
        self.after_read = after_read

    async def __aiter__(self):
        yield self.body
        if self.after_read is not None:
            self.after_read()

    async def aclose(self) -> None:
        return None


def response_body(model: str, text: str, sequence: int, *, final_result: bool = False) -> bytes:
    if final_result:
        output = [{
            "id": f"fc_fixture_{sequence}", "type": "function_call",
            "status": "completed", "call_id": f"call_fixture_{sequence}",
            "name": "final_result", "arguments": text,
        }]
    else:
        output = [{
            "id": f"msg_fixture_{sequence}", "type": "message", "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }]
    response = {
        "id": f"resp_fixture_{sequence}", "created_at": 1, "model": model,
        "object": "response", "status": "completed", "parallel_tool_calls": False,
        "tool_choice": "auto", "tools": [], "output": output,
    }
    return json.dumps(response, separators=(",", ":")).encode("utf-8")


def fixture_response(
    request: httpx.Request,
    status: int,
    body: bytes,
    after_read: Callable[[], Any] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"content-type": "application/json", "content-length": str(len(body))},
        stream=FixtureBytes(body, after_read),
        request=request,
    )
