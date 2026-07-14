"""编排写入入口的阶段前置条件门禁。"""

from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.services.exceptions import ServiceError


def ensure_expected_phase(
    task: Task,
    expected_phase: str | None,
) -> None:
    """拒绝基于旧 Task 快照重复提交的启动或单步推进。"""

    if (
        expected_phase is not None
        and task.current_phase != expected_phase
    ):
        raise ServiceError(
            "orchestration_phase_changed",
            "任务阶段已变化，请刷新后再推进编排。",
            409,
            {
                "expected_phase": expected_phase,
                "actual_phase": task.current_phase,
            },
        )
