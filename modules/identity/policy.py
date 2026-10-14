"""Versioned P1 action ceilings; a role name alone never supplies a grant."""

from collections.abc import Iterable
from typing import get_args

from modules.identity.errors import IdentityError
from packages.contracts.p0.identity_contracts import Action
from packages.contracts.p1.identity_requests import GrantableAction


POLICY_REVISION = 1
_TASK_CONTROL = frozenset(get_args(GrantableAction)) - {"resource.read"}
OWNER_ACTIONS = _TASK_CONTROL | {"resource.read", "project.manage"}
ROLE_ACTIONS = {
    "developer": _TASK_CONTROL | {"resource.read"},
    "reviewer": frozenset({"resource.read"}),
}
AGENT_ACTIONS = _TASK_CONTROL | {"resource.read"}
SUPPORTED_ACTIONS = OWNER_ACTIONS


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
