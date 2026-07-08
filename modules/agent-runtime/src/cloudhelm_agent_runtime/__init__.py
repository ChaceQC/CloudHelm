"""CloudHelm Agent Runtime。

本包提供 M4 范围内的 Requirement、Architect 和 Planner Agent。Agent
只负责把真实输入转换为可校验结构化对象，数据库持久化和状态迁移由
Platform API / Orchestrator 完成。
"""

__all__ = ["__version__"]

__version__ = "0.3.0"
