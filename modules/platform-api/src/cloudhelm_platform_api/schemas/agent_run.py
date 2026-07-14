"""AgentRun API DTO。"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.common import AgentRunStatus, OrmModel


class AgentRunCreate(BaseModel):
    """开发/内部联调用 AgentRun 创建请求体。

    M2 该接口只写入运行记录，不表示 Agent 已具备自动执行能力。
    """

    agent_type: str = Field(min_length=1, description="Agent 类型。")
    status: AgentRunStatus = Field(default=AgentRunStatus.PENDING, description="运行状态。")
    model_name: str | None = Field(default=None, description="模型名称。")
    prompt_hash: str | None = Field(default=None, description="Prompt 哈希。")
    summary: str | None = Field(default=None, description="结构化输出或失败摘要。")
    structured_output_type: str | None = Field(default=None, description="结构化输出类型。")
    structured_output_json: dict[str, Any] | None = Field(default=None, description="结构化输出 JSON。")
    error_code: str | None = Field(default=None, description="失败错误码。")
    error_message: str | None = Field(default=None, description="失败错误信息。")
    input_tokens: int = Field(default=0, ge=0, description="输入 token 数。")
    output_tokens: int = Field(default=0, ge=0, description="输出 token 数。")
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0, description="估算成本。")


class ProviderRequestUsageRead(BaseModel):
    """一次真实供应商请求的 token/cache usage。"""

    response_id: str | None = Field(description="供应商 response ID。")
    prompt_cache_key: str | None = Field(description="本次请求使用的缓存路由键。")
    input_tokens: int = Field(ge=0, description="本次请求输入 token。")
    cached_input_tokens: int = Field(ge=0, description="本次请求真实缓存 token。")
    output_tokens: int = Field(ge=0, description="本次请求输出 token。")
    cache_hit: bool = Field(description="是否由 cached_input_tokens > 0 推导命中。")


class AgentRunRead(OrmModel):
    """AgentRun 响应结构。"""

    id: UUID
    task_id: UUID
    conversation_id: UUID | None
    conversation_turn: int | None
    agent_type: str
    status: AgentRunStatus
    workflow_step: str | None
    attempt: int | None
    idempotency_key: str | None
    model_name: str | None
    prompt_hash: str | None
    summary: str | None
    structured_output_type: str | None
    structured_output_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    provider_request_count: int
    provider_requests: list[ProviderRequestUsageRead]
    provider_response_id: str | None
    prompt_cache_key: str | None
    cost_usd: Decimal
    started_at: datetime
    finished_at: datetime | None
