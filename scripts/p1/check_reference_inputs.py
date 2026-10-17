"""One disposable real reference import and atomic initial engineering Task binding."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from sqlalchemy import func, select

from database.commands import commands
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import read_fact_source, read_registered_reference, reference_key
from modules.collaboration.reference_inputs import REQUIRED_CAPABILITIES, RESOURCE_SCOPE_ID, ReferenceTaskApplication
from modules.collaboration.tables import task_declarations, task_fact_sources, task_inputs, task_reference_records, tasks
from modules.identity.errors import IdentityError
from modules.projects.reference_assets import ASSET_PATHS, load_reference_assets
from modules.workspaces.source_import import ReferenceSourceImporter
from packages.contracts.p1.identity_requests import DisableUserRequest
from packages.contracts.p1.source_requests import ImportReferenceSourceRequest
from packages.contracts.p1.task_facts import (
    AcceptanceMetadata, HumanPolicyMetadata, InputSetMetadata, ResourcePolicyMetadata, SourceMetadata,
)
from scripts.p1.check_source_commands import (
    OWNER, PROJECT, SourceCommandCheckFailure, SourceProbe, reject, require,
)
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture

ROOT = Path(__file__).resolve().parents[2]
METHOD_REVISION = "p1-real-reference-task-input-r1"


def snapshot(probe):
    with UnitOfWork(probe.pools.control) as uow:
        return tuple(uow.connection.scalar(select(func.count()).select_from(table)) for table in (
            task_fact_sources, task_reference_records, task_declarations, tasks, task_inputs, commands,
        ))


def assert_binding(probe, result, registration):
    with UnitOfWork(probe.pools.control) as uow:
        row = uow.connection.execute(select(tasks).where(tasks.c.task_id == result.task_id)).mappings().one()
        bound = uow.connection.execute(select(task_inputs).where(task_inputs.c.task_id == result.task_id)).mappings().one()
        declaration, reference = result.inputs.declaration, result.inputs.input_set_ref
        require(row["state"] == "draft" and row["version"] == 2 and row["control_revision"] == 0
                and row["input_validity_revision"] == 1 and row["completion_report_id"] is None,
                "reference_task_initial_state_invalid")
        require(bound["input_set_key"] == reference_key(PROJECT, reference)
                and bound["source_key"] == reference_key(PROJECT, registration.source_ref)
                and bound["candidate_key"] is None and bound["human_conclusion_key"] is None,
                "reference_task_initial_binding_invalid")
        input_record = read_registered_reference(uow.connection, PROJECT, reference)
        require(isinstance(input_record.metadata, InputSetMetadata)
                and len(input_record.metadata.input_set.references) == 6,
                "reference_task_exact_input_set_missing")
        assets = load_reference_assets(ROOT)
        kinds = {}
        for ref in input_record.metadata.input_set.references:
            record = read_registered_reference(uow.connection, PROJECT, ref)
            producer = read_fact_source(uow.connection, PROJECT, record.source_id)
            require(producer.purpose == "product", "reference_task_used_protocol_fixture")
            expected = {"requirement": "projects", "source": "projects", "method": "integration",
                        "acceptance_assets": "integration", "resource_policy": "identity", "human_policy": "identity"}
            require(producer.producer_domain == expected[record.metadata.record_kind], "reference_producer_domain_invalid")
            kinds[record.metadata.record_kind] = record.metadata
        require(kinds["requirement"] == assets.requirement, "real_requirement_not_registered")
        require(isinstance(kinds["source"], SourceMetadata)
                and kinds["source"].commit == registration.source_ref.revision
                and declaration.source_ref == registration.source_ref, "real_import_source_not_consumed")
        require(isinstance(kinds["acceptance_assets"], AcceptanceMetadata)
                and kinds["acceptance_assets"].required_check_ids == assets.required_check_ids
                and kinds["method"] == assets.method, "independent_acceptance_not_registered")
        require(isinstance(kinds["resource_policy"], ResourcePolicyMetadata)
                and kinds["resource_policy"].resource_scope_ids == (RESOURCE_SCOPE_ID,)
                and kinds["resource_policy"].allowed_capabilities == REQUIRED_CAPABILITIES,
                "development_resource_declaration_invalid")
        require(isinstance(kinds["human_policy"], HumanPolicyMetadata)
                and not kinds["human_policy"].is_completion_gate and not kinds["human_policy"].skip_allowed,
                "human_policy_or_conclusion_fabricated")
        require(uow.connection.scalar(select(func.count()).select_from(task_reference_records).where(
            task_reference_records.c.record_kind.in_(("candidate", "evidence", "human_conclusion")),
        )) == 0, "reference_task_created_acceptance_facts")
        require(len(assets.file_digests) == 4 and tuple(path for path, _ in assets.file_digests) == ASSET_PATHS,
                "reference_asset_allowlist_not_verified")
        return len(assets.required_check_ids)


def run_checks(fixture):
    probe = importer = None
    scene = "reference_task_fixture_failed"
    try:
        probe = SourceProbe(fixture)
        assets = load_reference_assets(ROOT)
        scene = "reference_task_real_import_failed"
        accepted = probe.app.import_reference(probe.actor, PROJECT, ImportReferenceSourceRequest(
            expected_project_revision=1,
        ), idempotency_key="real-reference-task-source")
        require(accepted.status_code == 202, "reference_task_source_intent_failed")
        repositories = fixture.runtime_dir / "reference-input-sources"
        repositories.mkdir(mode=0o700)
        importer = ReferenceSourceImporter(repositories, ROOT, probe.worker.resolve_import_operation)
        receipt = importer.import_reference(accepted.body.operation_id)
        registration = probe.worker.finish_import(accepted.body.operation_id, importer)
        require(receipt.import_commit == registration.source_ref.revision
                and receipt.file_count == 32 and receipt.import_commit != receipt.seed_commit,
                "reference_task_source_not_physically_imported")
        application = ReferenceTaskApplication(probe.pools.normal, ROOT)
        kwargs = {"expected_project_revision": accepted.body.project_revision,
                  "idempotency_key": "real-reference-task-initial"}
        scene = "reference_task_atomic_rollback_failed"
        before = snapshot(probe)
        reject(lambda: application.create(probe.actor, PROJECT, registration, **{
            **kwargs, "expected_project_revision": 0,
        }), TaskBoundaryError, "resource_revision_conflict")
        require(snapshot(probe) == before, "reference_task_rejection_leaked_registration")
        scene = "reference_task_initial_binding_failed"
        result = application.create(probe.actor, PROJECT, registration, **kwargs)
        require(result.created.status_code == 201 and result.bound.status_code == 200,
                "reference_task_create_or_bind_rejected")
        check_count = assert_binding(probe, result, registration)
        after = snapshot(probe)
        require(application.create(probe.actor, PROJECT, registration, **kwargs) == result
                and snapshot(probe) == after, "reference_task_replay_duplicated_state")
        scene = "reference_task_digest_conflict_failed"
        reject(lambda: application.create(probe.actor, PROJECT, registration, title="changed same-key request", **kwargs),
               TaskBoundaryError, "idempotency_digest_conflict")
        require(snapshot(probe) == after, "reference_task_conflict_changed_state")
        scene = "reference_task_current_identity_failed"
        probe.maintenance.disable_user(DisableUserRequest(user_id=OWNER))
        reject(lambda: application.create(probe.actor, PROJECT, registration, **kwargs), IdentityError, "authentication_failed")
        return {
            "real_import_file_count": receipt.file_count, "fixed_public_asset_count": len(assets.file_digests),
            "registered_independent_check_count": check_count, "real_registered_source_consumed": True,
            "product_producer_domains_verified": True, "atomic_registration_create_and_initial_binding": True,
            "rejected_create_rolls_back_input_registration": True, "stable_replay_and_digest_conflict": True,
            "current_identity_before_replay": True, "no_candidate_acceptance_result_or_human_conclusion": True,
            "resource_scope_is_declaration_only": RESOURCE_SCOPE_ID,
        }
    except SourceCommandCheckFailure as failure:
        failure.scene = scene
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
    parser.add_argument("--port", type=int, default=55437)
    args = parser.parse_args()
    report = {"method_revision": METHOD_REVISION, "mode": "development_worktree", "complete_scope": False,
              "started_at_utc": datetime.now(UTC).isoformat(),
              "scope": "real fixed-reference import, public-asset registration and draft Task initial binding; no physical admission"}
    try:
        with database_fixture(port=args.port) as fixture:
            report["fixture_id"] = fixture.project_name
            report["checks"] = run_checks(fixture)
        report.update(status="passed", cleanup="complete")
    except (SourceCommandCheckFailure, DatabaseFixtureError) as failure:
        report.update(status="failed", failure_code=str(failure))
        if hasattr(failure, "scene"):
            report["failure_scene"] = failure.scene
    except Exception:
        report.update(status="failed", failure_code="reference_task_verifier_failed")
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
