"""Fixed synthetic migration-contract checks; no database or container activity."""

import json
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.p0.migration_contracts import (
    MigrationBinding, MigrationPlan, MigrationQueryResult, MigrationRetryGate,
    P0MigrationContracts, check_migration_query, check_migration_retry, migration_succeeded,
)

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def _reject(action: Callable[[], object], code: str | None = None) -> None:
    try:
        action()
    except ValueError as error:
        if code is not None and str(error) != code:
            raise AssertionError("unexpected_migration_rejection") from None
        return
    raise AssertionError("invalid_migration_contract_accepted")


def run_checks() -> dict[str, bool]:
    plan = MigrationPlan(
        step_id="migrate-notes", plan_digest=DIGEST, control_revision=2,
        input_set_digest=DIGEST, database_instance_id="notes-db", schema_name="public",
        migration_artifact_digest=DIGEST, start_revision=None,
        target_revision="0002_add_updated_at_index", execution_lock_id="migration:notes-db",
        backup_mode="empty_target_verified", backup_evidence_ref="empty-target-fixture",
        compatibility_mode="fresh_install", compatibility_evidence_ref="fresh-install-fixture",
        postconditions_digest=DIGEST, revisions=(
            {"revision": "0001_create_notes", "down_revision": None,
             "script_digest": DIGEST, "change_kinds": ("create_table",)},
            {"revision": "0002_add_updated_at_index", "down_revision": "0001_create_notes",
             "script_digest": OTHER_DIGEST, "change_kinds": ("create_index",)},
        ),
    )
    binding = MigrationBinding(operation_id="operation-fixture", step_id=plan.step_id,
                               request_digest=DIGEST)
    common = dict(
        binding=binding, plan_digest=plan.plan_digest, database_instance_id=plan.database_instance_id,
        schema_name=plan.schema_name, migration_artifact_digest=plan.migration_artifact_digest,
        observed_at="2026-10-14T00:00:00Z",
    )
    evidence = dict(
        executor_ledger_complete=True, database_ledger_complete=True,
        database_revision_observed=True, executor_evidence_ref="executor-fixture",
        database_evidence_ref="database-fixture", physical_evidence_ref="physical-fixture",
    )
    checks = tuple({"check_id": name, "outcome": "passed", "evidence_ref": name + "-fixture"}
                   for name in ("schema_integrity", "data_integrity", "application_probe"))
    unknown = MigrationQueryResult(**common, status="unknown", observation_id="observe-unknown",
                                   actual_heads=(plan.target_revision,))
    unstarted = MigrationQueryResult(
        **common, **evidence, status="not_started", observation_id="observe-unstarted",
        process_state="absent", lock_state="free",
        never_started_evidence_ref="no-start-fence-fixture",
    )
    running = MigrationQueryResult(
        **common, **evidence, status="running", observation_id="observe-running",
        attempt_id="attempt-fixture",
        process_state="running", lock_state="held_by_operation", database_running=True,
    )
    succeeded = MigrationQueryResult(
        **common, **evidence, status="succeeded", observation_id="observe-succeeded",
        attempt_id="attempt-fixture",
        process_state="stopped", lock_state="free", actual_heads=(plan.target_revision,),
        postconditions_digest=DIGEST, postchecks=checks,
    )
    failed = MigrationQueryResult(
        **common, **evidence, status="failed_known", observation_id="observe-failed",
        attempt_id="attempt-fixture",
        process_state="stopped", lock_state="free", postconditions_digest=DIGEST,
        postchecks=tuple({**item, "outcome": "not_run"} for item in checks),
        failure_ref="transaction-failure-fixture", known_effects_ref="rollback-observed-fixture",
    )
    for result in (unstarted, running, succeeded, failed, unknown):
        assert check_migration_query(plan, binding, result) == result.status
        assert migration_succeeded(plan, binding, result) == (result.status == "succeeded")
    _reject(lambda: migration_succeeded(plan, binding, succeeded.model_copy(
        update={"actual_heads": ("0001_create_notes",)})), "MIGRATION_HEAD_MISMATCH")
    _reject(lambda: check_migration_query(plan, binding, succeeded.model_copy(
        update={"postchecks": ()})), "MIGRATION_POSTCHECKS_INCOMPLETE")
    _reject(lambda: check_migration_query(plan, binding, unstarted.model_copy(
        update={"database_ledger_complete": False})), "MIGRATION_QUERY_EVIDENCE_INCOMPLETE")
    _reject(lambda: check_migration_query(plan, binding, unstarted.model_copy(
        update={"never_started_evidence_ref": None})), "MIGRATION_NOT_STARTED_UNPROVEN")
    for changed in ({"operation_id": "other-operation"}, {"step_id": "other-step"},
                    {"request_digest": OTHER_DIGEST}):
        other = binding.model_copy(update=changed)
        _reject(lambda other=other: check_migration_query(plan, binding, unknown.model_copy(
            update={"binding": other})), "MIGRATION_QUERY_BINDING_MISMATCH")
    for change in ({"mode": "non_transactional"}, {"mode": "arbitrary_shell"},
                   {"direction": "downgrade"}, {"boundary": "dbos_system"},
                   {"postgres_version": "17.0"}, {"max_runtime_seconds": 601},
                   {"command": "synthetic-unapproved-command"}):
        _reject(lambda change=change: MigrationPlan.model_validate({**plan.model_dump(), **change}))
    revisions = [item.model_dump() for item in plan.revisions]
    _reject(lambda: MigrationPlan.model_validate({**plan.model_dump(), "revisions": (
        revisions[0], {**revisions[1], "down_revision": None},
    )}))
    _reject(lambda: MigrationPlan.model_validate({**plan.model_dump(), "revisions": (
        revisions[0], {**revisions[1], "change_kinds": ("drop_table",)},
    )}))
    upgraded = MigrationPlan.model_validate({
        **plan.model_dump(), "start_revision": "0001_create_notes", "backup_mode": "restore_verified",
        "compatibility_mode": "old_and_new_compatible",
    })
    assert upgraded.target_revision == plan.target_revision
    gate = MigrationRetryGate(
        binding=binding, plan_digest=DIGEST, control_revision=2, observation_id=unstarted.observation_id,
        authorized=True, approval_current=True, inputs_current=True, preconditions_verified=True,
        resources_reserved=True, fresh_permit_valid=True, start_lock_held=True,
        old_grants_closed=True, no_conflicting_execution=True,
    )
    check_migration_retry(plan, binding, unstarted, gate)
    for result in (unknown, running, succeeded, failed):
        _reject(lambda result=result: check_migration_retry(plan, binding, result, gate),
                "MIGRATION_RETRY_REQUIRES_NOT_STARTED")
    _reject(lambda: check_migration_retry(plan, binding, unstarted, gate.model_copy(
        update={"old_grants_closed": False})), "MIGRATION_RETRY_GATE_CLOSED")
    _reject(lambda: check_migration_retry(plan, binding, unstarted, gate.model_copy(
        update={"control_revision": 3})), "MIGRATION_RETRY_BINDING_STALE")
    _reject(lambda: check_migration_retry(plan, binding, unstarted, gate.model_copy(
        update={"observation_id": "older-observation"})), "MIGRATION_RETRY_BINDING_STALE")
    P0MigrationContracts(plan=plan, binding=binding, query_result=unknown, retry_gate=gate)
    return {
        "five_authoritative_results": True, "unknown_never_implies_success": True,
        "actual_head_and_postchecks_required": True, "absence_is_not_unstarted": True,
        "original_operation_step_digest_required": True, "unsupported_modes_rejected": True,
        "only_verified_unstarted_can_retry": True, "current_retry_gate_required": True,
    }


if __name__ == "__main__":
    print(json.dumps({"scope": "p0-decisions-r1/migrations", "checks": run_checks()}, ensure_ascii=False))
