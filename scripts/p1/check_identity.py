"""Real identity/HTTP checks on the coordinator's already initialized P1 fixture."""

from datetime import timedelta
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from pydantic import SecretStr
from sqlalchemy import func, select, update

from database.commands import commands
from database.connection import create_engine_from_settings
from database.uow import UnitOfWork
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.identity.tables import device_sessions, users
from modules.projects.tables import projects
from modules.sync.tables import event_log, outbox
from packages.contracts.p1.identity_results import MaintenanceResult
from scripts.p1.database_fixture import DatabaseFixture

_ROOT = Path(__file__).resolve().parents[2]
_PREFIX = "p11-identity"
_OWNER, _DEV, _OTHER = (f"{_PREFIX}-{name}" for name in ("owner", "developer", "outsider"))
_PROJECT, _FOREIGN = f"{_PREFIX}-project", f"{_PREFIX}-foreign"


class IdentityCheckFailure(RuntimeError):
    """Only fixed check codes may leave this verifier."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise IdentityCheckFailure(code)


class IdentityProbe:
    def __init__(self, fixture: DatabaseFixture) -> None:
        self.fixture = fixture
        self.private_dir = fixture.runtime_dir / "identity-credentials"
        self.tokens: dict[str, SecretStr] = {}
        self.receipts: dict[str, dict] = {}
        self.outputs: list[str] = []
        self.api_engine = create_engine_from_settings(fixture.settings("api"), purpose="control")
        self.worker_engine = None
        self.maintenance_engine = None

    def close(self) -> None:
        for engine in (self.worker_engine, self.maintenance_engine, self.api_engine):
            if engine is not None:
                engine.dispose()

    def cli(self, *arguments: str, expected: str | None = None, as_api: bool = False) -> dict:
        environment = os.environ.copy()
        environment.pop("CLOUDHELM_MIGRATOR_DATABASE_URL", None)
        reference = self.fixture.environment_for("api" if as_api else "migrator")
        environment["CLOUDHELM_MIGRATOR_DATABASE_URL_FILE"] = next(iter(reference.values()))
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "modules.identity.cli", *arguments], cwd=_ROOT,
            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        self.outputs.extend((completed.stdout, completed.stderr))
        if expected is None:
            _require(completed.returncode == 0, "identity_cli_failed")
            return MaintenanceResult.model_validate_json(completed.stdout).model_dump(mode="json", exclude_none=True)
        _require(completed.returncode != 0 and completed.stdout == "", "identity_cli_rejection_missing")
        result = json.loads(completed.stderr)
        _require(result == {"code": expected}, "identity_cli_rejection_invalid")
        return result

    def issue(self, label: str, user_id: str, *, lifetime: int = 28800) -> None:
        path = self.private_dir / label
        receipt = self.cli("issue-session", "--user-id", user_id, "--credential-file", str(path),
                           "--lifetime-seconds", str(lifetime))
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                 and info.st_uid == os.geteuid() and info.st_size == 48, "identity_credential_file_mode")
        token = SecretStr(path.read_text(encoding="utf-8").strip())
        _require(token.get_secret_value().startswith("ch1_"), "identity_credential_shape")
        self.tokens[label], self.receipts[label] = token, receipt

    def http(self, client, method: str, path: str, label: str, *, expected: int = 200,
             body: dict | None = None, raw: bytes | None = None, key: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.tokens[label].get_secret_value()}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        arguments = {"headers": headers}
        if raw is not None:
            headers["Content-Type"] = "application/json"
            arguments["content"] = raw
        elif body is not None:
            arguments["json"] = body
        response = client.request(method, path, **arguments)
        _require(response.status_code == expected, "identity_http_status_mismatch")
        for token in self.tokens.values():
            _require(token.get_secret_value() not in response.text and token.get_secret_value() not in str(response.headers),
                     "identity_credential_in_response")
        _require(response.headers.get("cache-control") == "no-store", "identity_cache_policy_missing")
        return response.json()

    def session_count(self) -> int:
        with UnitOfWork(self.api_engine) as uow:
            return uow.connection.scalar(select(func.count()).select_from(device_sessions).where(
                device_sessions.c.user_id == _OWNER,
            ))

    def once(self, command_id: str) -> None:
        with UnitOfWork(self.api_engine) as uow:
            amounts = [
                uow.connection.scalar(select(func.count()).select_from(commands).where(commands.c.command_id == command_id)),
                uow.connection.scalar(select(func.count()).select_from(event_log).where(event_log.c.command_id == command_id)),
                uow.connection.scalar(select(func.count()).select_from(outbox.join(event_log)).where(event_log.c.command_id == command_id)),
            ]
        _require(amounts == [1, 1, 1], "identity_command_event_outbox_not_once")

    def worker_access(self, command_id: str, action: str, *, denied: str | None = None) -> None:
        if self.worker_engine is None:
            self.worker_engine = create_engine_from_settings(self.fixture.settings("worker"), purpose="control")
        with UnitOfWork(self.worker_engine) as uow:
            actor = actor_for_command(uow, command_id)
            scope = actor.source_scope
            _require(scope.project_id == _PROJECT, "identity_recorded_scope_invalid")
            if scope.resource_kind == "project":
                revision = uow.connection.scalar(select(projects.c.revision).where(projects.c.project_id == _PROJECT))
            else:
                from modules.collaboration.tables import tasks
                revision = uow.connection.scalar(select(tasks.c.version).where(tasks.c.task_id == scope.resource_id))
            resource = AuthoritativeResource(scope.project_id, scope.resource_kind, scope.resource_id,
                                             revision=revision, target=actor.source_target)
            try:
                authorize_current(uow, actor, resource, action)
            except IdentityError as error:
                _require(error.code == denied, "identity_recorded_actor_wrong_denial")
            else:
                _require(denied is None, "identity_recorded_actor_not_revoked")


def _prepare(probe: IdentityProbe) -> dict[str, bool]:
    probe.cli("create-user", "--user-id", f"{_PREFIX}-unprivileged", "--display-name", "Unprivileged",
              as_api=True, expected="maintenance_role_required")
    with UnitOfWork(probe.api_engine) as uow:
        _require(uow.connection.scalar(select(users.c.user_id).where(
            users.c.user_id == f"{_PREFIX}-unprivileged")) is None, "identity_unprivileged_user_created")
    for user_id, name in ((_OWNER, "Identity owner"), (_DEV, "Identity developer"), (_OTHER, "Identity outsider")):
        result = probe.cli("create-user", "--user-id", user_id, "--display-name", name)
        _require(result["outcome"] == "created", "identity_user_not_created")
    for project_id, owner in ((_PROJECT, _OWNER), (_FOREIGN, _OTHER)):
        result = probe.cli("create-project", "--project-id", project_id, "--owner-user-id", owner, "--name", "Identity fixture")
        _require(result["outcome"] == "created", "identity_project_not_created")
    for label, user_id in (("owner", _OWNER), ("developer", _DEV), ("outsider", _OTHER)):
        probe.issue(label, user_id)
    probe.issue("expired", _OWNER, lifetime=60)
    info = probe.private_dir.stat()
    _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "identity_credential_directory_mode")
    return {"maintenance_role_required": True, "maintenance_users_projects_sessions": True, "credential_private_modes": True}


def _file_rejections(probe: IdentityProbe) -> dict[str, bool]:
    original = (probe.private_dir / "owner").read_bytes()
    count = probe.session_count()
    probe.cli("issue-session", "--user-id", _OWNER, "--credential-file", str(probe.private_dir / "owner"),
              expected="credential_file_exists")
    link = probe.private_dir / "symlink-token"
    link.symlink_to(probe.private_dir / "owner")
    probe.cli("issue-session", "--user-id", _OWNER, "--credential-file", str(link), expected="credential_file_exists")
    directory_link = probe.fixture.runtime_dir / "identity-directory-link"
    directory_link.symlink_to(probe.private_dir, target_is_directory=True)
    probe.cli("issue-session", "--user-id", _OWNER, "--credential-file", str(directory_link / "not-created"),
              expected="credential_file_write_failed")
    _require(probe.session_count() == count and (probe.private_dir / "owner").read_bytes() == original
             and not (probe.private_dir / "not-created").exists(), "identity_credential_overwrite")
    return {"credential_overwrite_and_symlink_rejected": True}


def _authentication(probe: IdentityProbe, client) -> dict[str, bool]:
    _require(probe.http(client, "GET", "/api/auth/me", "owner")["user_id"] == _OWNER, "identity_user_mismatch")
    _require(probe.http(client, "GET", f"/api/projects/{_FOREIGN}", "outsider")["owner_user_id"] == _OTHER,
             "identity_foreign_project_owner")
    probe.http(client, "GET", f"/api/projects/{_PROJECT}", "outsider", expected=403)
    probe.http(client, "GET", f"/api/projects/{_FOREIGN}", "owner", expected=403)
    probe.maintenance_engine = create_engine_from_settings(probe.fixture.settings("migrator"), purpose="maintenance")
    with UnitOfWork(probe.maintenance_engine) as uow:
        now = uow.connection.scalar(select(func.clock_timestamp()))
        changed = uow.connection.execute(update(device_sessions).where(
            device_sessions.c.session_id == probe.receipts["expired"]["session_id"], device_sessions.c.user_id == _OWNER,
        ).values(issued_at=now - timedelta(seconds=120), expires_at=now - timedelta(seconds=60)))
        _require(changed.rowcount == 1, "identity_expiry_fixture_missing")
    probe.http(client, "GET", "/api/auth/me", "expired", expected=401)
    return {"valid_authentication": True, "expired_authentication_denied": True, "cross_project_denied": True}


def _rename(probe: IdentityProbe, client) -> str:
    path = f"/api/projects/{_PROJECT}"
    before = probe.http(client, "GET", path, "owner")
    body = {"expected_project_revision": before["revision"], "name": "Identity renamed"}
    key = f"{_PREFIX}-rename"
    first = probe.http(client, "PATCH", path, "owner", body=body, key=key)
    replay = probe.http(client, "PATCH", path, "owner", body=body, key=key)
    conflict = probe.http(client, "PATCH", path, "owner", body={**body, "name": "Other name"}, key=key, expected=409)
    _require(first == replay and conflict["code"] == "idempotency_digest_conflict", "identity_rename_dedupe")
    _require(probe.http(client, "GET", path, "owner")["revision"] == before["revision"] + 1, "identity_rename_version")
    probe.once(first["command_id"])
    return first["command_id"]


def _grant(probe: IdentityProbe, client) -> str:
    before = probe.http(client, "GET", f"/api/projects/{_PROJECT}", "owner")
    body = {"expected_project_revision": before["revision"], "expected_permission_revision": before["permission_revision"],
            "user_id": _DEV, "role": "developer", "actions": ["resource.read", "task.command"]}
    path, key = f"/api/projects/{_PROJECT}/role-bindings", f"{_PREFIX}-grant"
    first = probe.http(client, "POST", path, "owner", body=body, key=key)
    replay = probe.http(client, "POST", path, "owner", body=body, key=key)
    conflict = probe.http(client, "POST", path, "owner", body={**body, "actions": ["resource.read"]}, key=key, expected=409)
    _require(first == replay and conflict["code"] == "idempotency_digest_conflict", "identity_grant_dedupe")
    current = probe.http(client, "GET", f"/api/projects/{_PROJECT}", "owner")
    _require(current["revision"] == before["revision"] + 1 and current["permission_revision"] == before["permission_revision"] + 1,
             "identity_grant_version")
    probe.http(client, "PATCH", f"/api/projects/{_PROJECT}", "developer", expected=403,
               body={"expected_project_revision": current["revision"], "name": "Forbidden"}, key=f"{_PREFIX}-forbidden")
    probe.once(first["command_id"])
    return first["role_binding"]["binding_id"]


def _developer_command(probe: IdentityProbe, client) -> tuple[dict, dict, str]:
    from scripts.p1.task_fixture import prepare_task_declaration

    declaration = prepare_task_declaration(probe.fixture, _PROJECT, probe.tokens["owner"])
    project = probe.http(client, "GET", f"/api/projects/{_PROJECT}", "owner")
    body = {"expected_project_revision": project["revision"], "declaration": declaration.model_dump(mode="json")}
    key = f"{_PREFIX}-developer-create"
    created = probe.http(client, "POST", f"/api/projects/{_PROJECT}/tasks", "developer", body=body, key=key, expected=201)
    _require(created["outcome"] == "created", "identity_developer_task_missing")
    probe.worker_access(created["command_id"], "task.command")
    probe.http(client, "POST", f"/api/tasks/{created['task_id']}/cancel", "developer", expected=403,
               body={"expected_version": created["version"], "expected_control_revision": created["control_revision"],
                     "cancel_reason": "identity-permission-check"}, key=f"{_PREFIX}-forbidden-cancel")
    current = probe.http(client, "GET", f"/api/tasks/{created['task_id']}", "developer")
    _require(current["version"] == created["version"] and current["cancellation"] is None, "identity_cancel_changed_task")
    return created, body, key


def _input_boundaries(probe: IdentityProbe, client) -> dict[str, bool]:
    path = f"/api/projects/{_PROJECT}"
    revision = probe.http(client, "GET", path, "owner")["revision"]
    marker = "identity-private-input-marker"
    invalid = [
        f'{{"expected_project_revision":{revision},"name":"safe","name":"{marker}"}}'.encode(),
        b'{"expected_project_revision":NaN,"name":"safe"}',
        json.dumps({"expected_project_revision": revision, "name": "safe", "allowed": True,
                    "caller": {"subject_id": _OWNER}, "secret": marker}).encode(),
    ]
    for index, raw in enumerate(invalid):
        response = probe.http(client, "PATCH", path, "owner", raw=raw, key=f"{_PREFIX}-invalid-{index}", expected=422)
        _require(marker not in json.dumps(response) and response["code"] == "request_schema_invalid", "identity_input_echo")
    _require(probe.http(client, "GET", path, "owner")["revision"] == revision, "identity_invalid_input_mutated")
    return {"strict_json_and_private_input_redaction": True}


def _revoke(probe: IdentityProbe, client, binding_id: str, developer: tuple[dict, dict, str]) -> dict[str, bool]:
    before = probe.http(client, "GET", f"/api/projects/{_PROJECT}", "owner-next")
    body = {"expected_project_revision": before["revision"], "expected_permission_revision": before["permission_revision"],
            "binding_id": binding_id}
    path, key = f"/api/projects/{_PROJECT}/role-bindings/revoke", f"{_PREFIX}-revoke"
    first = probe.http(client, "POST", path, "owner-next", body=body, key=key)
    replay = probe.http(client, "POST", path, "owner-next", body=body, key=key)
    conflict = probe.http(client, "POST", path, "owner-next", body={**body, "binding_id": f"{_PREFIX}-missing"}, key=key, expected=409)
    _require(first == replay and conflict["code"] == "idempotency_digest_conflict", "identity_revoke_dedupe")
    current = probe.http(client, "GET", f"/api/projects/{_PROJECT}", "owner-next")
    _require(current["revision"] == before["revision"] + 1 and current["permission_revision"] == before["permission_revision"] + 1,
             "identity_revoke_version")
    _require(first["role_binding"]["revoked"] is True, "identity_binding_not_revoked")
    probe.once(first["command_id"])
    created, original_body, original_key = developer
    probe.http(client, "POST", f"/api/projects/{_PROJECT}/tasks", "developer", body=original_body, key=original_key, expected=403)
    probe.worker_access(created["command_id"], "task.command", denied="permission_denied")
    return {"role_revoke_idempotency_once": True, "current_authorization_before_success_replay": True,
            "role_revocation_blocks_recorded_actor": True}


def _run(probe: IdentityProbe) -> dict[str, bool]:
    from scripts.p1.runtime_processes import api_running

    checks = {**_prepare(probe), **_file_rejections(probe)}
    with api_running(probe.fixture, instance="identity") as api:
        client = api.client
        checks.update(_authentication(probe, client))
        rename_command = _rename(probe, client)
        binding_id = _grant(probe, client)
        developer = _developer_command(probe, client)
        checks.update(_input_boundaries(probe, client))
        probe.issue("owner-next", _OWNER)
        probe.cli("revoke-session", "--session-id", probe.receipts["owner"]["session_id"])
        probe.http(client, "GET", "/api/auth/me", "owner", expected=401)
        probe.worker_access(rename_command, "project.manage")
        checks.update(_revoke(probe, client, binding_id, developer))
        probe.cli("disable-user", "--user-id", _OWNER)
        probe.http(client, "GET", "/api/auth/me", "owner-next", expected=401)
        probe.worker_access(rename_command, "project.manage", denied="identity_not_current")
    for token in probe.tokens.values():
        _require(all(token.get_secret_value() not in output for output in probe.outputs), "identity_cli_credential_echo")
    checks.update({"credential_not_in_cli_outputs": True, "rename_idempotency_once": True,
                   "role_grant_idempotency_once": True, "role_action_and_cancel_permission_denied": True,
                   "revoked_session_denied": True, "session_revocation_preserves_recorded_origin": True,
                   "disabled_user_blocks_recorded_actor": True})
    return checks


def run_checks(fixture: DatabaseFixture) -> dict[str, bool]:
    """The caller owns the one real database; this group never creates another one."""
    probe = None
    try:
        _require(isinstance(fixture, DatabaseFixture) and fixture.baseline is not None, "identity_initialized_fixture_required")
        probe = IdentityProbe(fixture)
        return _run(probe)
    except IdentityCheckFailure:
        raise
    except Exception:
        raise IdentityCheckFailure("identity_checks_failed") from None
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                raise IdentityCheckFailure("identity_check_cleanup_failed") from None


if __name__ == "__main__":
    raise SystemExit("identity_checks_require_shared_fixture")
