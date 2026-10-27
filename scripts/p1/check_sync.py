"""One isolated PostgreSQL/HTTP check of snapshot, committed dispatch and access."""

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update

from database.connection import create_business_pools, create_engine_from_settings
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.identity.authentication import authenticate_current
from modules.identity.bootstrap import IdentityMaintenance
from modules.identity.errors import IdentityError
from modules.identity.tables import project_policies
from modules.projects.commands import ProjectApplication
from modules.sync.application import SyncApplication
from modules.sync.dispatch import dispatch_pending, stream_head
from modules.sync.tables import dispatch_events, outbox
from packages.contracts.p1.identity_requests import (
    CreateProjectRequest, CreateUserRequest, DisableUserRequest, IssueSessionRequest, RenameProjectRequest,
)
from scripts.p1.database_fixture import database_fixture


def expect_code(call, code):
    try:
        call()
    except (TaskBoundaryError, IdentityError) as error:
        assert error.code == code, "expected_" + code + "_actual_" + error.code
    else:
        raise AssertionError("expected_denial_missing")


def check(fixture):
    admin = create_engine_from_settings(fixture.settings("migrator"), purpose="maintenance")
    pools = create_business_pools(fixture.settings("api"))
    try:
        maintenance = IdentityMaintenance(admin)
        actors, bearers = {}, {}
        for user in ("sync-owner", "sync-outsider"):
            maintenance.create_user(CreateUserRequest(user_id=user, display_name=user))
            path = fixture.runtime_dir / (user + "-session")
            maintenance.issue_session(IssueSessionRequest(user_id=user, credential_file=str(path)))
            bearer = SecretStr(Path(path).read_text(encoding="utf-8").strip())
            with UnitOfWork(pools.control) as uow:
                actors[user] = authenticate_current(uow, bearer)
            bearers[user] = bearer
        maintenance.create_project(CreateProjectRequest(project_id="sync-project", owner_user_id="sync-owner", name="Initial"))
        owner, outsider = actors["sync-owner"], actors["sync-outsider"]
        sync = SyncApplication(pools.control, "epoch-a")
        project = ProjectApplication(pools.normal)
        first = sync.snapshot(owner, "sync-project")
        assert first.cursor == 0 and first.project.name == "Initial", "initial_snapshot_invalid"
        rename = project.rename(owner, "sync-project", RenameProjectRequest(expected_project_revision=1, name="Committed"),
                                idempotency_key="sync-rename")
        assert rename.status_code == 200, "rename_not_committed"
        before_dispatch = sync.snapshot(owner, "sync-project")
        assert before_dispatch.cursor == 0 and before_dispatch.project.name == "Committed", "undispatched_state_missing"
        # A lost dispatcher transaction must leave both cursor and Outbox unchanged.
        try:
            with UnitOfWork(pools.control) as uow:
                head = stream_head(uow.connection, "sync-project", lock=True)
                dispatch_pending(uow.connection, head)
                raise RuntimeError("rollback_probe")
        except RuntimeError as error:
            assert str(error) == "rollback_probe", "unexpected_dispatch_failure"
        with UnitOfWork(pools.control) as uow:
            assert uow.connection.scalar(select(func.count()).select_from(dispatch_events)) == 0, "dispatch_not_atomic"
            assert uow.connection.scalar(select(func.count()).select_from(outbox).where(outbox.c.dispatched_at.is_(None))) == 1
        args = (owner, "sync-project", first.stream_id, 0, first.project.permission_revision)
        with ThreadPoolExecutor(max_workers=2) as executor:
            batches = list(executor.map(lambda _: sync.poll(*args), range(2)))
        assert all(len(batch.events) == 1 and batch.cursor == 1 for batch in batches), "concurrent_dispatch_changed_identity"
        with UnitOfWork(pools.control) as uow:
            assert uow.connection.scalar(select(func.count()).select_from(dispatch_events)) == 1, "duplicate_dispatch"
        after = sync.snapshot(owner, "sync-project")
        assert after.cursor == 1 and after.project.revision == 2, "snapshot_cursor_state_mismatch"
        assert not sync.poll(owner, "sync-project", after.stream_id, 1, 1).events, "replay_not_bounded"
        expect_code(lambda: sync.poll(owner, "sync-project", after.stream_id, 2, 1), "snapshot_required")
        expect_code(lambda: SyncApplication(pools.control, "epoch-b").poll(*args), "snapshot_required")
        expect_code(lambda: sync.snapshot(outsider, "sync-project"), "permission_denied")
        app = importlib.import_module("services.hub-api.app").create_app()
        app.state.runtime = SimpleNamespace(pools=pools, sync_epoch="epoch-a")
        client = TestClient(app)
        headers = {"Authorization": "Bearer " + bearers["sync-owner"].get_secret_value()}
        assert client.get("/api/projects/sync-project/snapshot").status_code == 401, "anonymous_snapshot_allowed"
        response = client.get("/api/projects/sync-project/snapshot", headers=headers)
        assert response.status_code == 200 and response.json()["cursor"] == 1, "http_snapshot_invalid"
        # One finite stream also proves GET disconnect waiting survives the old 10s body deadline.
        response = client.get("/api/projects/sync-project/events", headers=headers,
            params={"stream_id": after.stream_id, "after": 1, "permission_revision": 1})
        assert response.status_code == 200 and response.text.count("event: batch") >= 6, "http_sse_incomplete"
        assert "payload" not in response.text and "token" not in response.text, "sse_not_metadata_only"
        with UnitOfWork(admin) as uow:
            uow.connection.execute(update(project_policies).where(project_policies.c.project_id == "sync-project")
                                   .values(authorization_revision=2))
        expect_code(lambda: sync.poll(owner, "sync-project", after.stream_id, 1, 1), "authorization_changed")
        maintenance.disable_user(DisableUserRequest(user_id="sync-owner"))
        expect_code(lambda: sync.poll(owner, "sync-project", after.stream_id, 1, 2), "authentication_failed")
        client.close()
        return {"migration": fixture.baseline.business_revision, "committed_snapshot": True,
                "dispatch_rollback": True, "concurrent_dedup": True, "cursor_reset": True,
                "current_authorization": True, "finite_http_sse": True}
    finally:
        pools.dispose()
        admin.dispose()


def main():
    started = datetime.now(UTC).isoformat()
    try:
        with database_fixture(port=55436) as fixture:
            result = check(fixture)
    except Exception as error:
        # Driver, request or credential contents are never printed.
        print(json.dumps({"status": "failed", "category": type(error).__name__,
                          "code": str(error) if isinstance(error, AssertionError) else "sync_probe_failed"}))
        return 1
    print(json.dumps({"method": "p1-sync-r1", "status": "passed", "started_at": started,
                      "finished_at": datetime.now(UTC).isoformat(), **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
