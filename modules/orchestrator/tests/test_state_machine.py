"""M4 状态机白盒测试。"""

import pytest

from cloudhelm_orchestrator.state_machine import M4Action, M4Phase, M4StateMachine, StateMachineError


def test_allowed_m4_transitions() -> None:
    """覆盖 M4 允许迁移。"""

    machine = M4StateMachine()

    assert machine.transition("Created", M4Phase.REQUIREMENT_CLARIFYING, "start").to_phase == M4Phase.REQUIREMENT_CLARIFYING
    assert machine.transition("RequirementClarifying", M4Phase.DESIGNING, "requirement ok").to_phase == M4Phase.DESIGNING
    assert machine.transition("Designing", M4Phase.PLANNING, "low risk").to_phase == M4Phase.PLANNING
    assert (
        machine.transition("Designing", M4Phase.WAITING_DESIGN_APPROVAL, "high risk").to_phase
        == M4Phase.WAITING_DESIGN_APPROVAL
    )
    assert (
        machine.transition("WaitingDesignApproval", M4Phase.PLANNING, "approved").to_phase
        == M4Phase.PLANNING
    )


def test_forbidden_transition_is_rejected() -> None:
    """禁止跳过需求或越过 M4 范围。"""

    machine = M4StateMachine()

    with pytest.raises(StateMachineError):
        machine.transition("Created", M4Phase.PLANNING, "skip")

    with pytest.raises(StateMachineError):
        machine.next_action("Implementing")


def test_next_action_waits_for_design_approval() -> None:
    """WaitingDesignApproval 必须等待人工审批通过。"""

    machine = M4StateMachine()

    assert machine.next_action("Created") == M4Action.START
    assert machine.next_action("RequirementClarifying") == M4Action.RUN_REQUIREMENT
    assert machine.next_action("Designing") == M4Action.RUN_ARCHITECT
    assert machine.next_action("WaitingDesignApproval") == M4Action.WAIT_FOR_DESIGN_APPROVAL
    assert machine.next_action("WaitingDesignApproval", design_approved=True) == M4Action.RESUME_PLANNING
    assert machine.next_action("Planning", plan_exists=True) == M4Action.STOP
