"""Workflow worker 的进程级依赖装配。"""

from functools import lru_cache

from cloudhelm_workflow_engine.config import get_workflow_settings
from cloudhelm_workflow_engine.database import get_session_factory
from cloudhelm_workflow_engine.handlers.release_candidate_reconcile import (
    ReleaseCandidateReconcileHandler,
)
from cloudhelm_workflow_engine.registry import (
    HandlerRegistration,
    HandlerRegistry,
)
from cloudhelm_workflow_engine.worker_service import WorkflowWorkerService


@lru_cache(maxsize=1)
def get_worker_service() -> WorkflowWorkerService:
    """构造只注册真实 reconcile handler 的进程级 worker service。"""

    settings = get_workflow_settings()
    session_factory = get_session_factory()
    registry = HandlerRegistry(
        [
            HandlerRegistration(
                job_type="release_candidate_reconcile",
                resource_type="release_candidate",
                side_effect_class="none",
                handler=ReleaseCandidateReconcileHandler(session_factory),
            )
        ]
    )
    return WorkflowWorkerService(
        settings=settings,
        session_factory=session_factory,
        registry=registry,
    )
