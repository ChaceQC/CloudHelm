"""Prompt Cache key 与 usage 元数据提取。"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.usage import (
    ProviderCallMetadata,
    ProviderRequestUsage,
)


def build_prompt_cache_key(
    model_name: str | None,
    agent_type: str,
    payload: BaseModel | None,
    conversation_id: str | None = None,
) -> str:
    """按 conversation/thread 生成稳定 key，让同一会话多轮路由一致。

    普通 Agent 类型不会参与 key；只有显式创建的新子 Agent conversation 才
    会得到新 key。UUID conversation id 本身不包含 prompt 正文，可以直接
    保留用于审计；超长或不安全标识才回退为哈希。
    """

    task_id = getattr(payload, "task_id", None)
    project_id = getattr(payload, "project_id", None)
    identity = str(conversation_id or task_id or project_id or agent_type)
    candidate = f"cloudhelm:{identity}"
    if len(candidate) <= 64 and all(character.isalnum() or character in ":-_" for character in candidate):
        return candidate
    digest = hashlib.sha256(f"{model_name}:{identity}".encode("utf-8")).hexdigest()[:32]
    return f"cloudhelm:{digest}"


def extract_call_metadata(response_payload: dict[str, Any], prompt_cache_key: str) -> ProviderCallMetadata:
    """从完成事件提取 token 与缓存命中，不保存输入正文。"""

    usage = response_payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    input_details = usage.get("input_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    response_id = (
        response_payload.get("id")
        if isinstance(response_payload.get("id"), str)
        else None
    )
    request_usage = ProviderRequestUsage(
        response_id=response_id,
        prompt_cache_key=prompt_cache_key,
        input_tokens=int(usage.get("input_tokens") or 0),
        cached_input_tokens=int(input_details.get("cached_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )
    return ProviderCallMetadata(
        response_id=response_id,
        prompt_cache_key=prompt_cache_key,
        input_tokens=request_usage.input_tokens,
        cached_input_tokens=request_usage.cached_input_tokens,
        output_tokens=request_usage.output_tokens,
        request_usages=(request_usage,),
    )


def combine_call_metadata(calls: list[ProviderCallMetadata]) -> ProviderCallMetadata | None:
    """聚合同一 AgentRun 内的格式修复重试 usage。

    供应商只对已完成 Responses 返回 usage；网络握手失败等没有 usage 的尝试
    不在这里伪造 token。最终 response id 取最后一次完成调用。
    """

    if not calls:
        return None
    last = calls[-1]
    request_usages = tuple(
        usage
        for call in calls
        for usage in (
            call.request_usages
            or (
                ProviderRequestUsage(
                    response_id=call.response_id,
                    prompt_cache_key=call.prompt_cache_key,
                    input_tokens=call.input_tokens,
                    cached_input_tokens=call.cached_input_tokens,
                    output_tokens=call.output_tokens,
                ),
            )
        )
    )
    return ProviderCallMetadata(
        response_id=last.response_id,
        prompt_cache_key=last.prompt_cache_key,
        input_tokens=sum(usage.input_tokens for usage in request_usages),
        cached_input_tokens=sum(
            usage.cached_input_tokens for usage in request_usages
        ),
        output_tokens=sum(usage.output_tokens for usage in request_usages),
        request_count=len(request_usages),
        request_usages=request_usages,
    )
