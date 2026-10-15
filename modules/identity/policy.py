"""Versioned P1 action ceilings; a role name alone never supplies a grant."""

from collections.abc import Iterable

from modules.identity.errors import IdentityError
from packages.contracts.p0.identity_contracts import Action


POLICY_REVISION = 1
_TASK_CONTROL = frozenset({
    "task.command", "task.cancel", "operation.query", "operation.stop",
    "operation.reconcile", "fact.archive",
})
# The implicit owner grant stays at the P1.1 baseline. New request choices must
# never extend bootstrap ownership or already stored role/delegation actions.
OWNER_ACTIONS = _TASK_CONTROL | {"resource.read", "project.manage"}
ENGINEERING_ACTIONS = frozenset({"workspace.write", "candidate.submit", "operation.request"})
ROLE_ACTIONS = {
    "developer": _TASK_CONTROL | {"resource.read"} | ENGINEERING_ACTIONS,
    "reviewer": frozenset({"resource.read"}),
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
