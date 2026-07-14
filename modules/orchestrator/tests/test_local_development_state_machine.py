"""M6 本地开发状态机白盒测试。"""

import pytest

from cloudhelm_orchestrator.local_development_state_machine import (
    LocalDevelopmentAction,
    LocalDevelopmentPhase,
    LocalDevelopmentStateMachine,
    LocalDevelopmentStateMachineError,
)


def test_local_development_happy_path_transitions() -> None:
    """覆盖已有 sample repo 的主路径迁移。"""

    machine = LocalDevelopmentStateMachine()
    path = [
        (
            LocalDevelopmentPhase.PLANNING,
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
            LocalDevelopmentPhase.REVIEWING,
            LocalDevelopmentPhase.SECURITY_SCANNING,
        ),
        (
            LocalDevelopmentPhase.SECURITY_SCANNING,
            LocalDevelopmentPhase.READY_FOR_PR,
        ),
        (
            LocalDevelopmentPhase.READY_FOR_PR,
            LocalDevelopmentPhase.PULL_REQUEST_CREATED,
        ),
    ]

    for current, target in path:
        transition = machine.transition(current, target, "pytest")
        assert transition.from_phase == current
        assert transition.to_phase == target


def test_scaffolding_branch_and_rework_transitions() -> None:
    """覆盖脚手架分支以及测试、评审和安全回退。"""

    machine = LocalDevelopmentStateMachine()

    assert machine.start_target(needs_scaffolding=True) == (
        LocalDevelopmentPhase.SCAFFOLDING
    )
    assert machine.start_target(needs_scaffolding=False) == (
        LocalDevelopmentPhase.IMPLEMENTING
    )
    assert machine.transition(
        "Planning",
        LocalDevelopmentPhase.SCAFFOLDING,
        "new project",
    ).to_phase == LocalDevelopmentPhase.SCAFFOLDING
    assert machine.transition(
        "Scaffolding",
        LocalDevelopmentPhase.IMPLEMENTING,
        "scaffold complete",
    ).to_phase == LocalDevelopmentPhase.IMPLEMENTING

    for current in (
        LocalDevelopmentPhase.TESTING,
        LocalDevelopmentPhase.REVIEWING,
        LocalDevelopmentPhase.SECURITY_SCANNING,
    ):
        transition = machine.transition(
            current,
            LocalDevelopmentPhase.IMPLEMENTING,
            "rework",
        )
        assert transition.to_phase == LocalDevelopmentPhase.IMPLEMENTING


def test_next_action_matches_each_local_development_phase() -> None:
    """每个阶段只暴露一个最小 run-next 动作。"""

    machine = LocalDevelopmentStateMachine()

    assert machine.next_action("Planning") == LocalDevelopmentAction.START
    assert machine.next_action("Scaffolding") == (
        LocalDevelopmentAction.RUN_SCAFFOLD
    )
    assert machine.next_action("Implementing") == LocalDevelopmentAction.RUN_CODER
    assert machine.next_action("Testing") == LocalDevelopmentAction.RUN_TESTER
    assert machine.next_action("Reviewing") == LocalDevelopmentAction.RUN_REVIEWER
    assert machine.next_action("SecurityScanning") == (
        LocalDevelopmentAction.RUN_SECURITY
    )
    assert machine.next_action("ReadyForPR") == (
        LocalDevelopmentAction.FINALIZE_LOCAL_PR
    )
    assert machine.next_action("PullRequestCreated") == LocalDevelopmentAction.STOP


def test_invalid_local_development_phase_and_transition_are_rejected() -> None:
    """禁止跳过门禁或把远端部署阶段混入 M6 状态机。"""

    machine = LocalDevelopmentStateMachine()

    with pytest.raises(LocalDevelopmentStateMachineError):
        machine.next_action("Deploying")
    with pytest.raises(LocalDevelopmentStateMachineError):
        machine.transition(
            "Planning",
            LocalDevelopmentPhase.TESTING,
            "skip implementation",
        )
    with pytest.raises(LocalDevelopmentStateMachineError):
        machine.transition(
            "ReadyForPR",
            LocalDevelopmentPhase.IMPLEMENTING,
            "unsupported rollback",
        )
