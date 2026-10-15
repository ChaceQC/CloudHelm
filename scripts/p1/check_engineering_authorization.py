"""Narrow engineering grant checks; no physical operation or Task input acceptance."""

import argparse
from datetime import datetime, timezone
import json
from typing import Callable

from pydantic import SecretStr
from sqlalchemy import select

from database.connection import create_engine_from_settings
from database.uow import UnitOfWork
from modules.identity.actors import AuthoritativeResource
from modules.identity.authentication import authenticate_current
from modules.identity.authorization import authorize_current
from modules.identity.bootstrap import IdentityMaintenance
from modules.identity.errors import IdentityError
from modules.identity.policy import (
    AGENT_ACTIONS, ENGINEERING_ACTIONS, OWNER_ACTIONS, ROLE_ACTIONS,
    validate_delegation_actions, validate_role_actions,
)
from modules.identity.tables import project_policies, role_bindings
from modules.projects.commands import ProjectApplication
from modules.projects.tables import projects
from packages.contracts.p0.identity_contracts import (
    AuthorizationEnvelope, CommandEnvelope, Principal, ResourceScope, check_command,
)
from packages.contracts.p1.identity_requests import (
    CreateProjectRequest, CreateUserRequest, GrantProjectRoleRequest,
    IssueSessionRequest, RevokeProjectRoleRequest,
)
from scripts.p1.database_fixture import DatabaseFixture, DatabaseFixtureError, database_fixture

METHOD_REVISION = "p1-engineering-authorization-r1"
_PREFIX = "p12-engineering-identity"
_PROJECT = f"{_PREFIX}-project"
_OLD_ACTIONS = (
    "resource.read", "task.command", "task.cancel", "operation.query",
    "operation.stop", "operation.reconcile", "fact.archive",
)
_ACTIONS = ("workspace.write", "candidate.submit", "operation.request")


class EngineeringAuthorizationFailure(RuntimeError):
    """Only fixed check categories leave this verifier."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EngineeringAuthorizationFailure(code)


def _reject(action: Callable[[], object], code: str | None = None) -> None:
    try:
        action()
    except (ValueError, IdentityError) as error:
        _require(code is None or str(error) == code, "engineering_wrong_rejection")
        return
    raise EngineeringAuthorizationFailure("engineering_rejection_missing")


def _p0_check(role: str, action: str) -> None:
    principal = Principal(kind="agent" if role == "agent" else "human",
                          subject_id="engineering-contract-subject",
                          delegator_id="engineering-contract-delegator" if role == "agent" else None)
    scope = ResourceScope(project_id=_PROJECT, resource_kind="project", resource_id=_PROJECT)
    command = CommandEnvelope(
        request_schema_revision="engineering-authorization-fixture-r1", caller=principal,
        scope=scope, target=scope, action=action, expected_resource_revision=1,
        command_id="engineering-contract-command", idempotency_key="engineering-contract-key",
        request_digest="sha256:" + "0" * 64,
    )
    authorization = AuthorizationEnvelope(
        caller=principal, scope=scope, target=scope, action=action, role=role,
        permission_revision=1, policy_revision=1, resource_revision=1,
        audit_session_id="engineering-contract-session", decision_id="engineering-contract-decision",
        allowed=True, delegation_current=role == "agent",
    )
    _require(check_command(command, authorization) == "new", "engineering_p0_ceiling_conflict")


def _contracts() -> dict[str, bool]:
    _require(OWNER_ACTIONS == set(_OLD_ACTIONS) | {"project.manage"}, "engineering_owner_grant_changed")
    _require(ENGINEERING_ACTIONS == set(_ACTIONS), "engineering_action_set_changed")
    _require(validate_role_actions("developer", _OLD_ACTIONS) == _OLD_ACTIONS,
             "engineering_old_role_expanded")
    _require(validate_delegation_actions(_OLD_ACTIONS) == _OLD_ACTIONS, "engineering_old_delegation_expanded")
    for role, actions in (*ROLE_ACTIONS.items(), ("agent", AGENT_ACTIONS), ("project_owner", OWNER_ACTIONS)):
        for action in actions:
            _p0_check(role, action)
    for action in _ACTIONS:
        request = GrantProjectRoleRequest(expected_project_revision=1, expected_permission_revision=1,
                                          user_id="engineering-contract-user", role="developer", actions=(action,))
        _require(request.actions == (action,), "engineering_request_actions_changed")
        _require(validate_role_actions("developer", (action,)) == (action,), "engineering_role_action_missing")
        _require(validate_delegation_actions((action,)) == (action,), "engineering_delegation_action_missing")
        _reject(lambda action=action: validate_role_actions("reviewer", (action,)), "role_action_denied")
    public = request.model_dump(mode="python")
    _reject(lambda: GrantProjectRoleRequest.model_validate({**public, "allowed": True}))
    _reject(lambda: GrantProjectRoleRequest.model_validate({**public, "secret_value": "forbidden-fixture"}))
    _reject(lambda: GrantProjectRoleRequest.model_validate({**public, "actions": ("step.execute",)}))
    _reject(lambda: GrantProjectRoleRequest.model_validate({**public, "actions": ("workspace.write",) * 2}))
    return {"request_allowlist_and_duplicate_rejections": True, "p0_role_ceilings_preserved": True,
            "old_owner_role_and_delegation_actions_preserved": True}


class EngineeringProbe:
    def __init__(self, fixture: DatabaseFixture) -> None:
        self.api_engine = create_engine_from_settings(fixture.settings("api"), purpose="control")
        self.maintenance_engine = create_engine_from_settings(fixture.settings("migrator"), purpose="maintenance")
        self.application = ProjectApplication(self.api_engine)
        self.resource = AuthoritativeResource(_PROJECT, "project", _PROJECT)
        self.actors = {}
        maintenance = IdentityMaintenance(self.maintenance_engine)
        try:
            for label in ("owner", "developer", "reviewer"):
                user_id = f"{_PREFIX}-{label}"
                maintenance.create_user(CreateUserRequest(user_id=user_id, display_name=label))
                credential = fixture.runtime_dir / "engineering-credentials" / label
                maintenance.issue_session(IssueSessionRequest(user_id=user_id, credential_file=str(credential)))
                token = SecretStr(credential.read_text(encoding="utf-8").strip())
                with UnitOfWork(self.api_engine) as uow:
                    self.actors[label] = authenticate_current(uow, token)
            maintenance.create_project(CreateProjectRequest(
                project_id=_PROJECT, owner_user_id=f"{_PREFIX}-owner", name="Engineering identity fixture",
            ))
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.api_engine.dispose()
        self.maintenance_engine.dispose()

    def revisions(self) -> dict[str, int]:
        with UnitOfWork(self.api_engine) as uow:
            row = uow.connection.execute(select(
                projects.c.revision, project_policies.c.authorization_revision,
            ).join(project_policies).where(projects.c.project_id == _PROJECT)).mappings().one()
            return {"expected_project_revision": row["revision"],
                    "expected_permission_revision": row["authorization_revision"]}

    def grant(self, label: str, role: str, actions: tuple[str, ...], key: str):
        request = GrantProjectRoleRequest(**self.revisions(), user_id=f"{_PREFIX}-{label}", role=role, actions=actions)
        return self.application.grant_role(self.actors["owner"], _PROJECT, request, idempotency_key=f"{_PREFIX}-{key}")

    def authorize(self, label: str, action: str, *, denied: bool = False):
        try:
            with UnitOfWork(self.api_engine) as uow:
                decision = authorize_current(uow, self.actors[label], self.resource, action)
        except IdentityError as error:
            _require(denied and error.code == "permission_denied", "engineering_authorization_wrong_denial")
            return None
        _require(not denied, "engineering_ungranted_action_allowed")
        return decision

    def binding(self, label: str):
        with UnitOfWork(self.api_engine) as uow:
            return uow.connection.execute(select(role_bindings).where(
                role_bindings.c.project_id == _PROJECT, role_bindings.c.user_id == f"{_PREFIX}-{label}",
            )).mappings().one()


def _runtime(probe: EngineeringProbe) -> dict[str, bool]:
    _require(probe.grant("developer", "developer", _OLD_ACTIONS, "old-developer").status_code == 200,
             "engineering_old_role_grant_failed")
    _require(probe.grant("reviewer", "reviewer", ("resource.read",), "reviewer").status_code == 200,
             "engineering_reviewer_grant_failed")
    for action in _ACTIONS:
        for label in ("owner", "developer", "reviewer"):
            probe.authorize(label, action, denied=True)
    _require(tuple(probe.binding("developer")["actions"]) == _OLD_ACTIONS, "engineering_stored_old_role_changed")
    refused = probe.grant("reviewer", "reviewer", _ACTIONS, "reviewer-escalation")
    _require(refused.status_code == 409 and refused.body.code == "role_action_denied",
             "engineering_reviewer_escalation_allowed")
    _require(tuple(probe.binding("reviewer")["actions"]) == ("resource.read",), "engineering_refused_grant_changed_role")
    # Each update must grant exactly its one requested action, with no implication
    # from task.command, operation.request, or a different engineering action.
    for index, action in enumerate(_ACTIONS):
        granted = probe.grant("developer", "developer", (action,), f"explicit-{index}")
        _require(granted.status_code == 200, "engineering_explicit_grant_failed")
        _require(tuple(probe.binding("developer")["actions"]) == (action,), "engineering_explicit_grant_expanded")
        for candidate in _ACTIONS:
            decision = probe.authorize("developer", candidate, denied=candidate != action)
            if decision is not None:
                _require(decision.envelope.role == "developer"
                         and decision.role_binding_id == granted.body.role_binding.binding_id
                         and decision.envelope.permission_revision == granted.body.project.permission_revision,
                         "engineering_grant_audit_binding_invalid")
    revoked = probe.application.revoke_role(probe.actors["owner"], _PROJECT, RevokeProjectRoleRequest(
        **probe.revisions(), binding_id=probe.binding("developer")["binding_id"],
    ), idempotency_key=f"{_PREFIX}-revoke")
    _require(revoked.status_code == 200, "engineering_role_revoke_failed")
    for action in _ACTIONS:
        probe.authorize("developer", action, denied=True)
    owner_grant = probe.grant("owner", "developer", _ACTIONS, "owner-explicit-developer")
    _require(owner_grant.status_code == 200, "engineering_owner_explicit_grant_failed")
    for action in _ACTIONS:
        _require(probe.authorize("owner", action).envelope.role == "developer", "engineering_owner_role_bypass")
    _require(probe.authorize("owner", "project.manage").envelope.role == "project_owner", "engineering_owner_control_changed")
    return {"stored_old_developer_and_owner_have_no_engineering_grant": True,
            "reviewer_escalation_rejected_without_binding_change": True,
            "each_explicit_engineering_grant_has_no_implied_actions": True,
            "current_grant_and_audit_revision_used": True, "revocation_blocks_engineering_actions": True,
            "owner_requires_explicit_developer_binding_for_engineering": True}


def run_checks(fixture: DatabaseFixture) -> dict[str, bool]:
    """Reuse a coordinator-owned fixture; validate no Task, build or operation result."""
    probe = None
    try:
        _require(isinstance(fixture, DatabaseFixture) and fixture.baseline is not None,
                 "engineering_initialized_fixture_required")
        checks = _contracts()
        probe = EngineeringProbe(fixture)
        checks.update(_runtime(probe))
        return checks
    except EngineeringAuthorizationFailure:
        raise
    except Exception:
        raise EngineeringAuthorizationFailure("engineering_authorization_checks_failed") from None
    finally:
        if probe is not None:
            probe.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=55436)
    args = parser.parse_args()
    report = {"method_revision": METHOD_REVISION, "mode": "development_worktree",
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "identity grants only; no physical engineering or product acceptance",
              "cleanup": "not_started"}
    try:
        with database_fixture(port=args.port) as fixture:
            report["fixture_id"] = fixture.project_name
            report["checks"] = run_checks(fixture)
        report.update(status="passed", cleanup="complete")
    except (EngineeringAuthorizationFailure, DatabaseFixtureError) as error:
        report.update(status="failed", failure_code=str(error))
    except Exception:
        report.update(status="failed", failure_code="engineering_authorization_verifier_failed")
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
