"""Migration conclusions stay bound to the original plan and operation."""

from pydantic import ValidationError

from packages.contracts.p0.migration_contracts import (
    MigrationBinding, MigrationPlan, MigrationQueryResult, migration_succeeded,
)

DIGEST = "sha256:" + "a" * 64


def _reject(action, reason: str) -> None:
    try:
        action()
    except (ValueError, ValidationError) as error:
        if reason in str(error):
            return
        raise AssertionError(f"unexpected rejection: {reason}") from error
    raise AssertionError(f"missing rejection: {reason}")


def run_checks() -> dict[str, bool]:
    plan = MigrationPlan(
        step_id="migrate", plan_digest=DIGEST, control_revision=2, input_set_digest=DIGEST,
        database_instance_id="database", schema_name="public", migration_artifact_digest=DIGEST,
        revisions=(
            {"revision": "r1", "down_revision": None, "script_digest": DIGEST, "change_kinds": ("create_table",)},
            {"revision": "r2", "down_revision": "r1", "script_digest": DIGEST, "change_kinds": ("create_index",)},
        ),
        start_revision=None, target_revision="r2", execution_lock_id="migration:database",
        backup_mode="empty_target_verified", backup_evidence_ref="empty-target",
        compatibility_mode="fresh_install", compatibility_evidence_ref="fresh-install",
        postconditions_digest=DIGEST,
    )
    binding = MigrationBinding(operation_id="operation", step_id="migrate", request_digest=DIGEST)
    unknown = MigrationQueryResult(
        binding=binding, plan_digest=DIGEST, database_instance_id="database", schema_name="public",
        migration_artifact_digest=DIGEST, status="unknown", observation_id="observation",
        observed_at="2026-10-14T00:00:00Z",
    )
    assert migration_succeeded(plan, binding, unknown) is False
    other = binding.model_copy(update={"operation_id": "other-operation"})
    _reject(lambda: migration_succeeded(plan, binding, unknown.model_copy(update={"binding": other})),
            "MIGRATION_QUERY_BINDING_MISMATCH")
    _reject(lambda: MigrationPlan.model_validate({**plan.model_dump(), "mode": "arbitrary_shell"}),
            "literal_error")
    return {"unknown_is_not_success_and_replay_identity_is_fixed": True, "unsupported_migration_mode_rejected": True}
