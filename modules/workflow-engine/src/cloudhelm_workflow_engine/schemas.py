"""Workflow Engine 进程内结果 DTO。"""

from dataclasses import dataclass
from uuid import UUID

from cloudhelm_platform_api.repositories.workflow_job_repository import (
    DispatchReservation,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    ReleaseCandidateReconcilePayload,
    ReleaseCandidateReconcileResult,
    WorkflowJobBrokerMessage,
)


@dataclass(frozen=True)
class PublishOutcome:
    """单条 reservation 的 broker publish 结果。"""

    reservation: DispatchReservation
    error_code: str | None

    @property
    def succeeded(self) -> bool:
        """是否已由 broker 接受。"""

        return self.error_code is None


@dataclass(frozen=True)
class DispatchCycleResult:
    """一次 dispatcher 扫描的审计摘要。"""

    reserved: int
    published: int
    deferred: int


@dataclass(frozen=True)
class WorkerExecutionResult:
    """一次 Celery delivery 对 PostgreSQL job 的处理结果。"""

    workflow_job_id: UUID
    outcome: str
    status: str | None


@dataclass(frozen=True)
class ReclaimBatchResult:
    """一次 stale scan 的收敛摘要。"""

    scanned: int
    reclaimed: int
    cancelled: int
    failed: int
    recovery_required: int


__all__ = [
    "DispatchCycleResult",
    "PublishOutcome",
    "ReclaimBatchResult",
    "ReleaseCandidateReconcilePayload",
    "ReleaseCandidateReconcileResult",
    "WorkerExecutionResult",
    "WorkflowJobBrokerMessage",
]
