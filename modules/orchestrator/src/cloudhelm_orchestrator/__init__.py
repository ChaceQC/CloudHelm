"""CloudHelm Orchestrator。

M4 阶段只提供 Requirement、Design 和 Planning 的显式状态机。状态迁移
结果由 Platform API service 负责持久化到 Task 和 EventLog。
"""

__all__ = ["__version__"]

__version__ = "0.3.0"
