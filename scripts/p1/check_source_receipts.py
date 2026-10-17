"""Real fixed-reference import plus Hub facts; temporary storage proves no business quota."""

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from sqlalchemy import func, select, text, update

from database.uow import UnitOfWork
from modules.collaboration.records import contract_digest, read_fact_source, read_registered_reference
from modules.collaboration.tables import task_fact_sources, task_reference_records
from modules.identity.errors import IdentityError
from modules.projects.source_operations import SourceImportError
from modules.projects.source_receipts import register_published_import, verify_published_import
from modules.projects.source_tables import project_git_sources
from modules.projects.tables import projects
from modules.sync.tables import event_log, outbox
from modules.workspaces.git_objects import managed_repository_slot
from modules.workspaces.source_import import ReferenceSourceImporter
from packages.contracts.p1.identity_requests import DisableUserRequest, RevokeSessionRequest
from packages.contracts.p1.source_requests import ImportReferenceSourceRequest
from packages.contracts.p1.task_facts import SourceMetadata
from scripts.p1.check_source_commands import (
    FOREIGN, OTHER, OWNER, PROJECT, SourceCommandCheckFailure, SourceProbe, reject, require,
)
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture

ROOT = Path(__file__).resolve().parents[2]


def facts(probe, project_id):
    with UnitOfWork(probe.maintenance_engine) as uow:
        values = [uow.connection.scalar(select(func.count()).select_from(table).where(condition)) for table, condition in (
            (project_git_sources, project_git_sources.c.project_id == project_id),
            (task_fact_sources, task_fact_sources.c.project_id == project_id),
            (task_reference_records, task_reference_records.c.project_id == project_id),
            (event_log, (event_log.c.project_id == project_id) & (event_log.c.event_type == "project.source_registered")),
        )]
        values.append(uow.connection.scalar(select(func.count()).select_from(outbox.join(event_log)).where(
            event_log.c.project_id == project_id, event_log.c.event_type == "project.source_registered",
        )))
        return values


def accept(probe, project_id, key):
    reply = probe.app.import_reference(probe.actor, project_id, ImportReferenceSourceRequest(
        expected_project_revision=1,
    ), idempotency_key=key)
    require(reply.status_code == 202, "source_receipt_intent_failed")
    return reply.body.operation_id


def real_registration(probe, importer):
    operation = accept(probe, PROJECT, "receipt-main")
    reject(lambda: probe.worker.finish_import(operation, importer), SourceImportError, "source_import_not_published")
    require(facts(probe, PROJECT) == [0, 0, 0, 0, 0], "unpublished_source_was_registered")
    receipt = importer.import_reference(operation)
    require(importer.query(operation).state == "published", "real_source_not_published")
    require(receipt.file_count == 32 and receipt.import_commit != receipt.seed_commit,
            "source_receipt_not_independent_reference_import")
    reject(lambda: probe.worker.finish_import(operation, receipt), SourceImportError, "trusted_source_importer_required")
    registered = probe.worker.finish_import(operation, importer)
    require(registered.source_record.source == receipt.source and registered.source_ref.revision == receipt.import_commit,
            "registered_source_identity_mismatch")
    require(facts(probe, PROJECT) == [1, 1, 2, 1, 1], "source_registration_not_atomic")
    require(probe.worker.finish_import(operation, importer) == registered
            and facts(probe, PROJECT) == [1, 1, 2, 1, 1], "source_registration_replay_changed_fact")
    view = probe.app.query(probe.actor, PROJECT, operation)
    require(view.state == "registered" and view.registration == registered, "registered_source_query_missing")
    with UnitOfWork(probe.worker_engine) as uow:
        reference = read_registered_reference(uow.connection, PROJECT, registered.source_ref)
        producer = read_fact_source(uow.connection, PROJECT, reference.source_id)
        method = read_registered_reference(uow.connection, PROJECT, producer.method_ref)
        require(isinstance(reference.metadata, SourceMetadata) and reference.metadata.commit == receipt.import_commit,
                "actual_source_commit_not_registered")
        require(registered.source_ref.digest == contract_digest(SourceMetadata(commit=receipt.import_commit))
                and registered.source_ref.digest != receipt.manifest_digest
                and registered.receipt_digest != registered.source_ref.digest,
                "git_manifest_and_metadata_digests_conflated")
        require(producer.producer_domain == "projects" and producer.purpose == "product"
                and producer.principal.subject_id == OWNER and method.metadata.record_kind == "method",
                "source_producer_or_method_invalid")
        require(uow.connection.scalar(text(
            "SELECT has_table_privilege(current_user, 'cloudhelm.project_git_sources', 'INSERT') "
            "AND NOT has_table_privilege(current_user, 'cloudhelm.project_git_sources', 'UPDATE,DELETE')"
        )), "worker_source_insert_permissions_invalid")
    return operation, receipt, registered


def receipt_conflict(probe, importer, repositories, operation, receipt, registered):
    path = repositories / managed_repository_slot(receipt.source) / "cloudhelm-import.json"
    original = path.read_bytes()
    changed = receipt.model_copy(update={"prepared_at": receipt.prepared_at + timedelta(seconds=1)})
    try:
        # Alter only this disposable fixture's physical receipt metadata. query still
        # verifies the real bare/files; the Hub must reject a changed receipt digest.
        path.write_bytes(changed.model_dump_json().encode("utf-8"))
        require(importer.query(operation).state == "published", "receipt_conflict_fixture_not_physically_verified")
        reject(lambda: probe.worker.finish_import(operation, importer),
               SourceImportError, "source_import_physical_digest_conflict")
        require(facts(probe, PROJECT) == [1, 1, 2, 1, 1], "physical_conflict_changed_registration")
    finally:
        path.write_bytes(original)
    require(probe.worker.finish_import(operation, importer) == registered, "original_receipt_not_reconciled")


def transaction_and_current_access(probe, importer):
    operation = accept(probe, FOREIGN, "receipt-rollback")
    receipt = importer.import_reference(operation)
    verified = verify_published_import(operation, importer)
    try:
        with UnitOfWork(probe.worker_engine) as uow:
            register_published_import(uow, operation, verified)
            raise SourceCommandCheckFailure("receipt_deliberate_rollback")
    except SourceCommandCheckFailure as failure:
        require(str(failure) == "receipt_deliberate_rollback", "source_receipt_rollback_failed")
    require(facts(probe, FOREIGN) == [0, 0, 0, 0, 0] and importer.query(operation).state == "published",
            "database_rollback_changed_physical_result_or_leaked_facts")
    with UnitOfWork(probe.maintenance_engine) as uow:
        uow.connection.execute(update(projects).where(projects.c.project_id == FOREIGN).values(owner_user_id=OTHER))
    try:
        with UnitOfWork(probe.worker_engine) as uow:
            reject(lambda: register_published_import(uow, operation, verified), IdentityError, "permission_denied")
    finally:
        with UnitOfWork(probe.maintenance_engine) as uow:
            uow.connection.execute(update(projects).where(projects.c.project_id == FOREIGN).values(owner_user_id=OWNER))
    require(facts(probe, FOREIGN) == [0, 0, 0, 0, 0], "late_permission_loss_registered_source")
    probe.maintenance.revoke_session(RevokeSessionRequest(session_id=probe.session.session_id))
    registered = probe.worker.finish_import(operation, importer)
    require(registered.source_ref.revision == receipt.import_commit and facts(probe, FOREIGN) == [1, 1, 2, 1, 1],
            "published_source_not_recovered_after_database_rollback")
    require(probe.worker.finish_import(operation, importer) == registered, "committed_result_loss_not_replayed")
    probe.maintenance.disable_user(DisableUserRequest(user_id=OWNER))
    reject(lambda: register_after_disable(probe, operation, verified), IdentityError, "identity_not_current")
    with UnitOfWork(probe.maintenance_engine) as uow:
        require(uow.connection.scalar(select(func.count()).select_from(task_reference_records).where(
            task_reference_records.c.record_kind.not_in(("method", "source")),
        )) == 0, "source_registration_created_other_engineering_facts")


def register_after_disable(probe, operation, verified):
    with UnitOfWork(probe.worker_engine) as uow:
        return register_published_import(uow, operation, verified)


def run_checks(fixture):
    probe = importer = None
    scene = "source_receipt_fixture_failed"
    try:
        probe = SourceProbe(fixture)
        repositories = fixture.runtime_dir / "source-repositories"
        repositories.mkdir(mode=0o700)
        importer = ReferenceSourceImporter(repositories, ROOT, probe.worker.resolve_import_operation)
        scene = "source_receipt_real_registration_failed"
        operation, receipt, registered = real_registration(probe, importer)
        scene = "source_receipt_physical_conflict_failed"
        receipt_conflict(probe, importer, repositories, operation, receipt, registered)
        scene = "source_receipt_transaction_and_access_failed"
        transaction_and_current_access(probe, importer)
        return {"real_reference_bare_and_manifest_verified": True, "actual_projects_source_metadata_registered": True,
                "worker_minimal_insert_permission": True, "independent_git_manifest_receipt_metadata_digests": True,
                "original_registration_replayed_once": True, "changed_physical_receipt_digest_rejected": True,
                "unpublished_and_raw_receipt_rejected": True, "short_transaction_rollback_preserves_physical_result": True,
                "late_permission_loss_and_disabled_user_rejected": True, "logout_does_not_cancel_accepted_import": True,
                "published_result_reconciled_after_database_rollback": True, "no_candidate_or_acceptance_fact_created": True}
    except SourceCommandCheckFailure:
        raise
    except Exception:
        raise SourceCommandCheckFailure(scene) from None
    finally:
        if importer is not None:
            importer.close()
        if probe is not None:
            probe.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=55435)
    args = parser.parse_args()
    report = {"method_revision": "p1-source-receipt-registration-r1", "mode": "development_worktree",
              "started_at_utc": datetime.now(UTC).isoformat(), "complete_scope": False,
              "scope": "real fixed-reference private import and Hub facts; no business storage admission or worker entry"}
    try:
        with database_fixture(port=args.port) as fixture:
            report["fixture_id"] = fixture.project_name
            report["checks"] = run_checks(fixture)
        report.update(status="passed", cleanup="complete")
    except (SourceCommandCheckFailure, DatabaseFixtureError) as failure:
        report.update(status="failed", failure_code=str(failure))
    except Exception:
        report.update(status="failed", failure_code="source_receipt_verifier_failed")
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
