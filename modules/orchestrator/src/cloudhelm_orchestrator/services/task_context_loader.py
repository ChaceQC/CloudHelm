"""Orchestrator 任务上下文协议。

Platform API 会从数据库加载这些上下文字段并交给 Agent Runtime。该文件
只定义边界类型，避免 orchestrator 直接依赖 SQLAlchemy ORM。
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TaskContext:
    """运行 M4 Agent 所需的最小任务上下文。"""

    task_id: UUID
    project_id: UUID
    title: str
    description: str
    source_type: str
    source_ref: str | None
    risk_level: str
    current_phase: str
