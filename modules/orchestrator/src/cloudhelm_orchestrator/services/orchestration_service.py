"""Orchestrator service 协议说明。

Platform API 中的 `cloudhelm_platform_api.services.orchestration_service`
负责实际事务。这里提供轻量依赖边界，供后续拆分为独立进程或 RPC 服务时
复用状态机契约。
"""

from dataclasses import dataclass

from cloudhelm_orchestrator.state_machine import M4Action, Transition


@dataclass(frozen=True)
class OrchestrationDecision:
    """一次编排决策。"""

    action: M4Action
    transition: Transition | None = None
    message: str | None = None
