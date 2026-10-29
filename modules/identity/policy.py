"""Versioned P1 action ceilings; a role name alone never supplies a grant."""

from collections.abc import Iterable

from modules.identity.errors import IdentityError
from packages.contracts.p0.identity_contracts import Action


POLICY_REVISION = 1
_TASK_CONTROL = frozenset({
    "task.command", "task.cancel", "operation.query", "operation.stop",
    "operation.reconcile", "fact.archive",
})
# D04 permits human owners to approve their own deployment. Engineering and
# stored delegation ceilings stay separate; agents cannot inherit approval.
HUMAN_TEST_ACTIONS = frozenset({
    "human_test.enter", "human_test.pass", "human_test.request_changes", "human_test.skip",
})
OWNER_ACTIONS = _TASK_CONTROL | {"resource.read", "project.manage", "deployment.approve", "review.submit"} | HUMAN_TEST_ACTIONS
ENGINEERING_ACTIONS = frozenset({"workspace.write", "candidate.submit", "operation.request"})
ROLE_ACTIONS = {
    "developer": _TASK_CONTROL | {"resource.read"} | ENGINEERING_ACTIONS,
    "reviewer": frozenset({"resource.read", "review.submit"}),
    "tester": frozenset({"resource.read"}) | HUMAN_TEST_ACTIONS,
    "deployment_approver": frozenset({"resource.read", "deployment.approve"}),
}
AGENT_ACTIONS = ROLE_ACTIONS["developer"]
SUPPORTED_ACTIONS = OWNER_ACTIONS | AGENT_ACTIONS


def validate_role_actions(role: str, actions: Iterable[Action]) -> tuple[Action, ...]:
    values = tuple(actions)
    ceiling = ROLE_ACTIONS.get(role)
    if (ceiling is None or not 1 <= len(values) <= 20
            or len(set(values)) != len(values) or not set(values) <= ceiling):
        raise IdentityError("role_action_denied")
    return values


def validate_delegation_actions(actions: Iterable[Action]) -> tuple[Action, ...]:
    values = tuple(actions)
    if (not 1 <= len(values) <= 20 or len(set(values)) != len(values)
            or not set(values) <= AGENT_ACTIONS):
        raise IdentityError("role_action_denied")
    return values
