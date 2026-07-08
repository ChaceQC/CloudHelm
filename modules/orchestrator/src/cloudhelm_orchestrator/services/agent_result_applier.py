"""Agent 结果应用协议。

真实结果应用在 Platform API service 中完成。本模块仅保留 M4 事件名称，
保证测试和文档引用同一组稳定字符串。
"""

from enum import Enum


class M4EventType(str, Enum):
    """M4 新增事件类型。"""

    TASK_PHASE_CHANGED = "TaskPhaseChanged"
    AGENT_RUN_STARTED = "AgentRunStarted"
    AGENT_RUN_COMPLETED = "AgentRunCompleted"
    AGENT_RUN_FAILED = "AgentRunFailed"
    REQUIREMENT_SPEC_CREATED = "RequirementSpecCreated"
    TECHNICAL_DESIGN_CREATED = "TechnicalDesignCreated"
    DEVELOPMENT_PLAN_CREATED = "DevelopmentPlanCreated"
    APPROVAL_REQUESTED = "ApprovalRequested"
