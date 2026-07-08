"""Agent 输入输出的通用类型。

这些类型不依赖 Platform API ORM，便于 agent-runtime 在独立测试环境中
验证结构化输出，同时让 Platform API 以 DTO 方式消费校验后的对象。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """CloudHelm M4 复用的风险等级。

    L0/L1 可在 M4 内自动推进；L2 及以上需要进入设计审批或后续工具审批。
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class AgentExecutionMetadata(BaseModel):
    """Agent 输出随附的审计元数据。

    Provider 只负责模型或规则化生成，不写数据库；该元数据由调用方写入
    `agent_runs`，用于追踪模型、prompt 版本和结构化输出类型。
    """

    provider: str = Field(description="生成输出的 provider 名称。")
    model_name: str | None = Field(default=None, description="外部模型名；本地 provider 可为空。")
    prompt_version: str = Field(default="m4-v1", description="Prompt 或规则版本。")
    generated_at: datetime | None = Field(default=None, description="生成时间；调用方可按需补齐。")
