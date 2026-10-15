"""Narrow source-intent checks; this method does not execute or register a Git import."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, text, update

from database.commands import CommandConflict, commands
from database.connection import create_business_pools, create_engine_from_settings
from database.models import load_business_metadata
from database.uow import UnitOfWork
from modules.identity.authentication import authenticate_current
from modules.identity.bootstrap import IdentityMaintenance
from modules.identity.errors import IdentityError
from modules.projects.source_commands import SourceImportApplication, accept_reference_import
from modules.projects.source_import_tables import project_source_imports
from modules.projects.source_operations import SourceImportError
from modules.projects.source_tables import project_git_sources
from modules.projects.tables import projects
from modules.sync.tables import event_log, outbox
from modules.workflow.tables import workflow_bindings
from modules.workspaces.source_import import reference_import_digest
from packages.contracts.p1.identity_requests import (
    CreateProjectRequest, CreateUserRequest, DisableUserRequest, IssueSessionRequest, RevokeSessionRequest,
)
from packages.contracts.p1.source_requests import ImportReferenceSourceRequest
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture

PREFIX = "p12-source-intent"
OWNER, OTHER = PREFIX + "-owner", PREFIX + "-other"
PROJECT, FOREIGN = PREFIX + "-project", PREFIX + "-foreign"


class SourceCommandCheckFailure(AssertionError):
    pass


def require(condition, code):
    if not condition:
        raise SourceCommandCheckFailure(code)


def reject(action, schema, code=None):
    try:
        action()
    except schema as failure:
        require(code is None or str(failure) == code, "source_command_wrong_rejection")
    else:
        raise SourceCommandCheckFailure("source_command_rejection_missing")


class SourceProbe:
    def __init__(self, fixture):
        self.pools = create_business_pools(fixture.settings("api"))
        self.maintenance_engine = create_engine_from_settings(fixture.settings("migrator"), purpose="maintenance")
        self.worker_engine = create_engine_from_settings(fixture.settings("worker"), purpose="control")
        self.maintenance = IdentityMaintenance(self.maintenance_engine)
        self.app = SourceImportApplication(self.pools.normal, self.pools.control)
        self.worker = SourceImportApplication(self.worker_engine, self.worker_engine)
        for user in (OWNER, OTHER):
            self.maintenance.create_user(CreateUserRequest(user_id=user, display_name="Source intent test fixture"))
        for project in (PROJECT, FOREIGN):
            self.maintenance.create_project(CreateProjectRequest(
                project_id=project, owner_user_id=OWNER, name="Source intent test fixture",
            ))
        self.session = self.maintenance.issue_session(IssueSessionRequest(
            user_id=OWNER, credential_file=str(fixture.runtime_dir / "source-command-credentials" / "owner"),
        ))
        token = SecretStr(Path(self.session.credential_file).read_text(encoding="utf-8").strip())
        with UnitOfWork(self.pools.control) as uow:
            self.actor = authenticate_current(uow, token)

    def close(self):
        self.worker_engine.dispose()
        self.maintenance_engine.dispose()
        self.pools.dispose()

    def snapshot(self, project_id):
        with UnitOfWork(self.pools.control) as uow:
            revision = uow.connection.scalar(select(projects.c.revision).where(projects.c.project_id == project_id))
            counts = [uow.connection.scalar(select(func.count()).select_from(table).where(condition)) for table, condition in (
                (project_source_imports, project_source_imports.c.project_id == project_id),
                (commands, commands.c.project_id == project_id),
                (event_log, event_log.c.project_id == project_id),
            )]
            counts.append(uow.connection.scalar(select(func.count()).select_from(outbox.join(event_log)).where(
                event_log.c.project_id == project_id,
            )))
            return revision, counts


def structure_and_contracts(probe):
    for field, value in (("url", "https://invalid.example"), ("path", "/tmp/private"),
                         ("allowed", True), ("success", True), ("reference_revision", "other-r1")):
        reject(lambda: ImportReferenceSourceRequest.model_validate({"expected_project_revision": 1, field: value}),
               ValidationError)
    metadata = load_business_metadata()
    with UnitOfWork(probe.maintenance_engine) as uow:
        context = MigrationContext.configure(uow.connection, opts={
            "include_schemas": True,
            "include_name": lambda name, kind, parent: kind != "schema" or name == "cloudhelm",
            "include_object": lambda obj, name, kind, reflected, compare_to:
                kind != "table" or name == "project_source_imports",
        })
        require(not compare_metadata(context, metadata), "source_import_metadata_migration_drift")
    for role, engine in (("api", probe.pools.control), ("worker", probe.worker_engine)):
        with UnitOfWork(engine) as uow:
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                require(not uow.connection.scalar(text(
                    "SELECT has_table_privilege(current_user, 'cloudhelm.project_source_imports', :privilege)"
                ), {"privilege": privilege}), "source_import_runtime_mutation_allowed")
            allowed = uow.connection.scalar(text(
                "SELECT has_table_privilege(current_user, 'cloudhelm.project_source_imports', 'INSERT')"
            ))
            require(allowed == (role == "api"), "source_import_insert_role_invalid")


def acceptance_and_replay(probe):
    stale = probe.app.import_reference(probe.actor, PROJECT, ImportReferenceSourceRequest(expected_project_revision=0),
                                       idempotency_key="source-stale")
    require(stale.status_code == 409 and stale.body.code == "resource_revision_conflict", "source_stale_version_allowed")
    before = probe.snapshot(PROJECT)
    value = ImportReferenceSourceRequest(expected_project_revision=before[0])
    first = probe.app.import_reference(probe.actor, PROJECT, value, idempotency_key="source-accept")
    require(first.status_code == 202 and first.body.outcome == "accepted"
            and first.body.code == "source_import_awaiting_executor", "source_acceptance_invalid")
    after = probe.snapshot(PROJECT)
    require(after == (before[0] + 1, [item + 1 for item in before[1]]), "source_acceptance_not_atomic")
    replay = probe.app.import_reference(probe.actor, PROJECT, value, idempotency_key="source-accept")
    require(replay == first and probe.snapshot(PROJECT) == after, "source_replay_changed_intent")
    reject(lambda: probe.app.import_reference(probe.actor, PROJECT, ImportReferenceSourceRequest(
        expected_project_revision=after[0],
    ), idempotency_key="source-accept"), CommandConflict, "idempotency_digest_conflict")
    denied = probe.app.import_reference(probe.actor, PROJECT, ImportReferenceSourceRequest(
        expected_project_revision=after[0],
    ), idempotency_key="source-second")
    require(denied.status_code == 409 and denied.body.code == "project_source_import_already_requested",
            "source_second_identity_allowed")
    view = probe.app.query(probe.actor, PROJECT, first.body.operation_id)
    spec = probe.worker.resolve_import_operation(first.body.operation_id)
    require(view.state == "accepted" and view.source == first.body.source == spec.source
            and view.request_digest == first.body.request_digest == reference_import_digest(spec),
            "source_original_intent_not_resolved")
    reject(lambda: probe.app.query(probe.actor, FOREIGN, first.body.operation_id),
           SourceImportError, "source_import_not_found")
    reject(lambda: probe.worker.resolve_import_operation("source-import-unknown"),
           SourceImportError, "source_import_not_found")
    return value, first


def rollback_and_authority(probe, value, first):
    before = probe.snapshot(FOREIGN)
    try:
        with UnitOfWork(probe.pools.normal) as uow:
            result = accept_reference_import(uow, probe.actor, FOREIGN, ImportReferenceSourceRequest(
                expected_project_revision=before[0],
            ), idempotency_key="source-rollback")
            require(result.status_code == 202, "source_uow_acceptance_failed")
            raise SourceCommandCheckFailure("source_deliberate_rollback")
    except SourceCommandCheckFailure as failure:
        require(str(failure) == "source_deliberate_rollback", "source_rollback_probe_failed")
    require(probe.snapshot(FOREIGN) == before, "source_uow_rollback_incomplete")
    with UnitOfWork(probe.maintenance_engine) as uow:
        uow.connection.execute(update(projects).where(projects.c.project_id == PROJECT).values(owner_user_id=OTHER))
    try:
        reject(lambda: probe.worker.resolve_import_operation(first.body.operation_id), IdentityError, "permission_denied")
        reject(lambda: probe.app.import_reference(probe.actor, PROJECT, value, idempotency_key="source-accept"),
               IdentityError, "permission_denied")
    finally:
        with UnitOfWork(probe.maintenance_engine) as uow:
            uow.connection.execute(update(projects).where(projects.c.project_id == PROJECT).values(owner_user_id=OWNER))
    probe.maintenance.revoke_session(RevokeSessionRequest(session_id=probe.session.session_id))
    require(probe.worker.resolve_import_operation(first.body.operation_id).source == first.body.source,
            "source_session_logout_cancelled_accepted_command")
    reject(lambda: probe.app.import_reference(probe.actor, PROJECT, value, idempotency_key="source-accept"),
           IdentityError, "authentication_failed")
    probe.maintenance.disable_user(DisableUserRequest(user_id=OWNER))
    reject(lambda: probe.worker.resolve_import_operation(first.body.operation_id), IdentityError, "identity_not_current")
    with UnitOfWork(probe.maintenance_engine) as uow:
        require(uow.connection.scalar(select(func.count()).select_from(project_git_sources)) == 0,
                "source_intent_claimed_registered_source")
        require(uow.connection.scalar(select(func.count()).select_from(workflow_bindings)) == 0,
                "source_intent_used_fake_enqueue")


def run_checks(fixture):
    probe = None
    scene = "source_command_fixture_setup_failed"
    try:
        probe = SourceProbe(fixture)
        scene = "source_command_structure_checks_failed"
        structure_and_contracts(probe)
        scene = "source_command_acceptance_checks_failed"
        value, first = acceptance_and_replay(probe)
        scene = "source_command_current_authority_checks_failed"
        rollback_and_authority(probe, value, first)
        return {"request_allowlist_and_migration": True, "immutable_runtime_intent_permissions": True,
                "current_access_before_replay": True, "stable_operation_identity_and_digest": True,
                "new_version_and_unique_source_reservation": True, "command_event_outbox_atomicity": True,
                "caller_uow_rollback": True, "cross_project_and_unknown_operation_rejected": True,
                "logout_preserves_accepted_authority": True, "ownership_loss_and_disabled_user_block_resolver": True,
                "no_fake_enqueue_or_registered_source": True}
    except SourceCommandCheckFailure:
        raise
    except Exception:
        raise SourceCommandCheckFailure(scene) from None
    finally:
        if probe is not None:
            probe.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=55435)
    args = parser.parse_args()
    report = {"method_revision": "p1-source-command-intent-r1", "mode": "development_worktree",
              "started_at_utc": datetime.now(UTC).isoformat(), "complete_scope": False,
              "scope": "source intent, current authority and rollback; no Git execution or receipt registration"}
    try:
        with database_fixture(port=args.port) as fixture:
            report["fixture_id"] = fixture.project_name
            report["checks"] = run_checks(fixture)
        report.update(status="passed", cleanup="complete")
    except (SourceCommandCheckFailure, DatabaseFixtureError) as failure:
        report.update(status="failed", failure_code=str(failure))
    except Exception:
        report.update(status="failed", failure_code="source_command_verifier_failed")
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
