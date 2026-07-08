"""M4 Orchestrator 显式状态机。

状态机保持为纯函数和轻量类，便于白盒测试覆盖允许迁移、禁止迁移和审批
分支。它不直接读写数据库，避免把事务边界散落在状态判断中。
"""

from dataclasses import dataclass
from enum import Enum


class M4Phase(str, Enum):
    """M4 覆盖的任务阶段。"""

    CREATED = "Created"
    REQUIREMENT_CLARIFYING = "RequirementClarifying"
    DESIGNING = "Designing"
    WAITING_DESIGN_APPROVAL = "WaitingDesignApproval"
    PLANNING = "Planning"


class M4Action(str, Enum):
    """M4 run-next 可执行动作。"""

    START = "start"
    RUN_REQUIREMENT = "run_requirement"
    RUN_ARCHITECT = "run_architect"
    WAIT_FOR_DESIGN_APPROVAL = "wait_for_design_approval"
    RESUME_PLANNING = "resume_planning"
    RUN_PLANNER = "run_planner"
    STOP = "stop"


class StateMachineError(ValueError):
    """非法状态迁移错误。"""


@dataclass(frozen=True)
class Transition:
    """状态迁移结果。

    `reason` 会写入 `TaskPhaseChanged` 事件，便于控制台回放和调试。
    """

    from_phase: M4Phase
    to_phase: M4Phase
    reason: str


class M4StateMachine:
    """M4 编排状态机。"""

    allowed_transitions: set[tuple[M4Phase, M4Phase]] = {
        (M4Phase.CREATED, M4Phase.REQUIREMENT_CLARIFYING),
        (M4Phase.REQUIREMENT_CLARIFYING, M4Phase.DESIGNING),
        (M4Phase.DESIGNING, M4Phase.WAITING_DESIGN_APPROVAL),
        (M4Phase.DESIGNING, M4Phase.PLANNING),
        (M4Phase.WAITING_DESIGN_APPROVAL, M4Phase.PLANNING),
    }

    def parse_phase(self, value: str) -> M4Phase:
        """把数据库中的阶段字符串转为 M4 枚举。"""

        try:
            return M4Phase(value)
        except ValueError as exc:
            raise StateMachineError(f"phase is outside M4 scope: {value}") from exc

    def transition(self, current: str | M4Phase, target: M4Phase, reason: str) -> Transition:
        """校验并返回迁移对象。"""

        current_phase = self.parse_phase(current) if isinstance(current, str) else current
        if (current_phase, target) not in self.allowed_transitions:
            raise StateMachineError(f"invalid M4 transition: {current_phase.value} -> {target.value}")
        return Transition(from_phase=current_phase, to_phase=target, reason=reason)

    def next_action(
        self,
        current: str | M4Phase,
        *,
        design_approved: bool = False,
        plan_exists: bool = False,
    ) -> M4Action:
        """根据当前阶段和审批/计划状态返回下一步动作。"""

        phase = self.parse_phase(current) if isinstance(current, str) else current
        if phase == M4Phase.CREATED:
            return M4Action.START
        if phase == M4Phase.REQUIREMENT_CLARIFYING:
            return M4Action.RUN_REQUIREMENT
        if phase == M4Phase.DESIGNING:
            return M4Action.RUN_ARCHITECT
        if phase == M4Phase.WAITING_DESIGN_APPROVAL:
            return M4Action.RESUME_PLANNING if design_approved else M4Action.WAIT_FOR_DESIGN_APPROVAL
        if phase == M4Phase.PLANNING:
            return M4Action.STOP if plan_exists else M4Action.RUN_PLANNER
        return M4Action.STOP
