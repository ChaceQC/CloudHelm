"""M6 本地开发闭环显式状态机。

本模块只描述 Planning 到本地等价 PR record 的阶段、动作和合法迁移。
数据库事务、Agent 执行、工具调用及事件写入继续由 Platform API service
负责，确保状态判断可独立进行白盒测试。
"""

from dataclasses import dataclass
from enum import Enum


class LocalDevelopmentPhase(str, Enum):
    """M6 本地代码实现、测试、审查和 PR record 阶段。"""

    PLANNING = "Planning"
    SCAFFOLDING = "Scaffolding"
    IMPLEMENTING = "Implementing"
    TESTING = "Testing"
    REVIEWING = "Reviewing"
    SECURITY_SCANNING = "SecurityScanning"
    READY_FOR_PR = "ReadyForPR"
    PULL_REQUEST_CREATED = "PullRequestCreated"


class LocalDevelopmentAction(str, Enum):
    """M6 run-next 在各阶段可执行的最小动作。"""

    START = "start_local_development"
    RUN_SCAFFOLD = "run_scaffold"
    RUN_CODER = "run_coder"
    RUN_TESTER = "run_tester"
    RUN_REVIEWER = "run_reviewer"
    RUN_SECURITY = "run_security"
    FINALIZE_LOCAL_PR = "finalize_local_pull_request"
    STOP = "stop"


class LocalDevelopmentStateMachineError(ValueError):
    """本地开发阶段或迁移不符合 M6 状态机时抛出的错误。"""


@dataclass(frozen=True)
class LocalDevelopmentTransition:
    """一次已校验的 M6 状态迁移。"""

    from_phase: LocalDevelopmentPhase
    to_phase: LocalDevelopmentPhase
    reason: str


class LocalDevelopmentStateMachine:
    """Planning 到本地 PR record 的纯状态机。"""

    allowed_transitions: set[
        tuple[LocalDevelopmentPhase, LocalDevelopmentPhase]
    ] = {
        (
            LocalDevelopmentPhase.PLANNING,
            LocalDevelopmentPhase.SCAFFOLDING,
        ),
        (
            LocalDevelopmentPhase.PLANNING,
            LocalDevelopmentPhase.IMPLEMENTING,
        ),
        (
            LocalDevelopmentPhase.SCAFFOLDING,
            LocalDevelopmentPhase.IMPLEMENTING,
        ),
        (
            LocalDevelopmentPhase.IMPLEMENTING,
            LocalDevelopmentPhase.TESTING,
        ),
        (
            LocalDevelopmentPhase.TESTING,
            LocalDevelopmentPhase.REVIEWING,
        ),
        (
            LocalDevelopmentPhase.TESTING,
            LocalDevelopmentPhase.IMPLEMENTING,
        ),
        (
            LocalDevelopmentPhase.REVIEWING,
            LocalDevelopmentPhase.SECURITY_SCANNING,
        ),
        (
            LocalDevelopmentPhase.REVIEWING,
            LocalDevelopmentPhase.IMPLEMENTING,
        ),
        (
            LocalDevelopmentPhase.SECURITY_SCANNING,
            LocalDevelopmentPhase.READY_FOR_PR,
        ),
        (
            LocalDevelopmentPhase.SECURITY_SCANNING,
            LocalDevelopmentPhase.IMPLEMENTING,
        ),
        (
            LocalDevelopmentPhase.READY_FOR_PR,
            LocalDevelopmentPhase.PULL_REQUEST_CREATED,
        ),
    }

    def parse_phase(self, value: str) -> LocalDevelopmentPhase:
        """把数据库阶段字符串解析为 M6 阶段枚举。"""

        try:
            return LocalDevelopmentPhase(value)
        except ValueError as exc:
            raise LocalDevelopmentStateMachineError(
                f"phase is outside M6 local development scope: {value}"
            ) from exc

    def transition(
        self,
        current: str | LocalDevelopmentPhase,
        target: LocalDevelopmentPhase,
        reason: str,
    ) -> LocalDevelopmentTransition:
        """校验迁移并返回不可变迁移对象。"""

        current_phase = (
            self.parse_phase(current) if isinstance(current, str) else current
        )
        if (current_phase, target) not in self.allowed_transitions:
            raise LocalDevelopmentStateMachineError(
                "invalid M6 local development transition: "
                f"{current_phase.value} -> {target.value}"
            )
        return LocalDevelopmentTransition(
            from_phase=current_phase,
            to_phase=target,
            reason=reason,
        )

    def start_target(self, *, needs_scaffolding: bool) -> LocalDevelopmentPhase:
        """根据仓库是否需要脚手架返回 Planning 的目标阶段。"""

        return (
            LocalDevelopmentPhase.SCAFFOLDING
            if needs_scaffolding
            else LocalDevelopmentPhase.IMPLEMENTING
        )

    def next_action(
        self,
        current: str | LocalDevelopmentPhase,
    ) -> LocalDevelopmentAction:
        """根据当前阶段返回下一个最小动作。"""

        phase = self.parse_phase(current) if isinstance(current, str) else current
        actions = {
            LocalDevelopmentPhase.PLANNING: LocalDevelopmentAction.START,
            LocalDevelopmentPhase.SCAFFOLDING: LocalDevelopmentAction.RUN_SCAFFOLD,
            LocalDevelopmentPhase.IMPLEMENTING: LocalDevelopmentAction.RUN_CODER,
            LocalDevelopmentPhase.TESTING: LocalDevelopmentAction.RUN_TESTER,
            LocalDevelopmentPhase.REVIEWING: LocalDevelopmentAction.RUN_REVIEWER,
            LocalDevelopmentPhase.SECURITY_SCANNING: LocalDevelopmentAction.RUN_SECURITY,
            LocalDevelopmentPhase.READY_FOR_PR: LocalDevelopmentAction.FINALIZE_LOCAL_PR,
            LocalDevelopmentPhase.PULL_REQUEST_CREATED: LocalDevelopmentAction.STOP,
        }
        return actions[phase]
