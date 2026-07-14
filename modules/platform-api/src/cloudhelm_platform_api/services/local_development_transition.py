"""M6 Task phase 更新与统一事件。"""

from cloudhelm_platform_api.services.event_service import EventService


def apply_task_transition(
    task,
    events: EventService,
    *,
    from_phase: str,
    to_phase: str,
    reason: str,
    actor_id: str,
) -> None:
    """更新 Task phase，并写不含业务正文的可审计事件。"""

    task.current_phase = to_phase
    events.record(
        "TaskPhaseChanged",
        "orchestrator",
        actor_id,
        {
            "task_id": str(task.id),
            "from": from_phase,
            "to": to_phase,
            "reason": reason,
        },
        task.id,
    )
