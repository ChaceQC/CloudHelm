"""M7 handler registry 与副作用分类。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

_SIDE_EFFECT_CLASSES = {
    "none",
    "external_idempotent",
    "external_uncertain",
}


class WorkflowHandler(Protocol):
    """worker 可调用的独立事务 handler。"""

    def execute(
        self,
        *,
        workflow_job_id: UUID,
        worker_owner: str,
    ):
        """执行并提交资源与 WorkflowJob 终态。"""


@dataclass(frozen=True)
class HandlerRegistration:
    """冻结 job/resource/side-effect 与实现对象的映射。"""

    job_type: str
    resource_type: str
    side_effect_class: str
    handler: WorkflowHandler

    def __post_init__(self) -> None:
        """拒绝未冻结的副作用分类，避免恢复策略静默降级。"""

        if self.side_effect_class not in _SIDE_EFFECT_CLASSES:
            raise ValueError("Workflow handler side_effect_class 非法。")


class HandlerRegistry:
    """只注册已真实实现并通过契约测试的 handler。"""

    def __init__(
        self,
        registrations: list[HandlerRegistration],
    ) -> None:
        self._items = {item.job_type: item for item in registrations}
        if len(self._items) != len(registrations):
            raise ValueError("Workflow handler job_type 重复。")

    def get(self, job_type: str) -> HandlerRegistration | None:
        """按 PostgreSQL job_type 读取不可变注册项。"""

        return self._items.get(job_type)
