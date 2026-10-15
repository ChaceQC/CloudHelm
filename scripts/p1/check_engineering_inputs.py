"""Narrow initial binding checks with registered test metadata; no real source acceptance."""

import argparse
from datetime import UTC, datetime
import json

from sqlalchemy import func, select, update

from database.commands import commands
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.input_commands import bind_initial_input_in_uow
from modules.collaboration.records import read_registered_reference, reference_key
from modules.collaboration.tables import task_fact_sources, task_inputs, task_reference_records
from modules.identity.errors import IdentityError
from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, input_set_digest
from packages.contracts.p1.identity_requests import DisableUserRequest
from packages.contracts.p1.task_facts import InputSetMetadata, MethodMetadata, SourceMetadata
from packages.contracts.p1.task_internal import BindInitialTaskInputRequest, InvalidateTaskInputRequest
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture
from scripts.p1.task_fixture import FixtureSources
from scripts.p1.task_probe import OWNER, PROJECT, TaskCheckFailure, TaskProbe, require

METHOD_REVISION = "p1-engineering-initial-input-r1"


def input_ref(probe, label: str, mutate=None):
    with UnitOfWork(probe.pools.control) as uow:
        source = FixtureSources(uow, PROJECT, probe.token)
        declaration = probe.declaration
        refs = (declaration.requirement_ref, declaration.acceptance_assets_ref, declaration.source_ref,
                declaration.resource_scope_ref, declaration.human_test_policy_ref, source.method_ref)
        if mutate is not None:
            refs = mutate(source, refs)
        value = InputSet(input_set_id=source.identity(label), references=refs, set_digest=input_set_digest(refs))
        return source.add(label, InputSetMetadata(input_set=value), domain="collaboration")


def request(probe, task_id, reference, **changes):
    row = probe.row(task_id)
    return BindInitialTaskInputRequest(**{
        "expected_version": row["version"], "expected_control_revision": row["control_revision"],
        "expected_input_validity_revision": row["input_validity_revision"], "input_set_ref": reference, **changes,
    })


def bind(probe, task_id, value, *, key=None, expected="task_initial_input_bound"):
    result = probe.app.bind_initial_input(probe.actor(), task_id, value,
                                         idempotency_key=key or probe.key("initial-input"))
    require(result.body.code == expected, "engineering_input_result_code_mismatch")
    require(result.status_code == (200 if expected == "task_initial_input_bound" else 409),
            "engineering_input_result_status_mismatch")
    return result


def row(probe, task_id):
    with UnitOfWork(probe.pools.control) as uow:
        values = uow.connection.execute(select(task_inputs).where(task_inputs.c.task_id == task_id)).mappings().all()
        require(len(values) <= 1, "engineering_initial_input_duplicated")
        return dict(values[0]) if values else None


def test_bindings(probe, reference):
    created = probe.create("engineering-initial-draft")
    value, key = request(probe, created.task_id, reference), probe.key("initial-replay")
    before = probe.snapshot(created.task_id)
    first = bind(probe, created.task_id, value, key=key)
    require(first.body.outcome == "input_bound" and first.body.state == "draft"
            and first.body.version == created.version + 1 and first.body.input_validity_revision == 1
            and first.body.control_revision == created.control_revision, "engineering_initial_revision_invalid")
    stored = row(probe, created.task_id)
    require(stored is not None and stored["input_set_key"] == reference_key(PROJECT, reference)
            and stored["source_key"] == reference_key(PROJECT, probe.declaration.source_ref)
            and stored["candidate_key"] is None and stored["human_conclusion_key"] is None,
            "engineering_initial_projection_invalid")
    after = probe.snapshot(created.task_id)
    require(all(after[1][field] == before[1][field] + 1 for field in ("commands", "events", "outbox"))
            and all(after[1][field] == before[1][field] for field in ("bindings", "items", "reports")),
            "engineering_initial_handoff_not_atomic")
    replay = bind(probe, created.task_id, value, key=key)
    require(replay == first and probe.snapshot(created.task_id) == after, "engineering_initial_replay_changed_result")
    bind(probe, created.task_id, request(probe, created.task_id, reference), expected="task_initial_input_already_bound")
    other_ref = input_ref(probe, "engineering-other-valid-input")
    try:
        bind(probe, created.task_id, BindInitialTaskInputRequest(**{
            **value.model_dump(), "input_set_ref": other_ref,
        }), key=key)
    except TaskBoundaryError:
        pass
    else:
        raise TaskCheckFailure("engineering_input_digest_reuse_allowed")
    started = probe.start(probe.create("engineering-initial-active"))
    bind(probe, started.task_id, request(probe, started.task_id, reference))
    require(row(probe, started.task_id) is not None, "engineering_active_input_missing")
    return created.task_id, value, key, first


def test_rejections(probe, reference):
    created = probe.create("engineering-invalid-input")
    for changes, code in (
        ({"expected_version": created.version + 1}, "resource_revision_conflict"),
        ({"expected_control_revision": 1}, "control_revision_conflict"),
        ({"expected_input_validity_revision": 1}, "input_validity_revision_conflict"),
    ):
        bind(probe, created.task_id, request(probe, created.task_id, reference, **changes), expected=code)
    unknown = EngineeringRef(kind="input_set", object_id="engineering-unregistered", revision="r1",
                             digest="sha256:" + "0" * 64, digest_algorithm="sha256")
    bind(probe, created.task_id, request(probe, created.task_id, unknown), expected="reference_not_registered")
    missing = input_ref(probe, "engineering-missing-method", lambda source, refs: refs[:-1])
    extra = input_ref(probe, "engineering-extra-input", lambda source, refs: (*refs, source.add(
        "engineering-unrelated-method", MethodMetadata(description="Test-only unrelated method"), domain="projects",
    )))
    replaced = input_ref(probe, "engineering-replaced-source", lambda source, refs: (
        *refs[:2], source.add("engineering-other-source", SourceMetadata(commit="2" * 40), domain="projects"), *refs[3:],
    ))
    for invalid in (missing, extra, replaced):
        bind(probe, created.task_id, request(probe, created.task_id, invalid), expected="initial_input_declaration_mismatch")
    require(row(probe, created.task_id) is None and probe.row(created.task_id)["version"] == created.version,
            "engineering_rejection_mutated_input")
    cancelled = probe.create("engineering-cancelled-input")
    probe.app.cancel(probe.actor(), cancelled.task_id, probe.cancel_request(cancelled.task_id),
                     idempotency_key=probe.key("engineering-cancel"))
    bind(probe, cancelled.task_id, request(probe, cancelled.task_id, reference), expected="task_progress_closed")


def test_source_and_rollback(probe, reference):
    created = probe.create("engineering-disabled-source")
    value, key = request(probe, created.task_id, reference), probe.key("disabled-source")
    with UnitOfWork(probe.pools.control) as uow:
        record = read_registered_reference(uow.connection, PROJECT, probe.declaration.source_ref)
        uow.connection.execute(update(task_fact_sources).where(
            task_fact_sources.c.project_id == PROJECT, task_fact_sources.c.source_id == record.source_id,
        ).values(enabled=False))
    try:
        denied = bind(probe, created.task_id, value, key=key, expected="fact_source_unavailable")
    finally:
        with UnitOfWork(probe.pools.control) as uow:
            uow.connection.execute(update(task_fact_sources).where(
                task_fact_sources.c.project_id == PROJECT, task_fact_sources.c.source_id == record.source_id,
            ).values(enabled=True))
    repeated = bind(probe, created.task_id, value, key=key, expected="fact_source_unavailable")
    require(repeated == denied and row(probe, created.task_id) is None, "engineering_rejected_replay_changed")
    fresh = probe.create("engineering-rollback-input")
    before, rollback_key = probe.snapshot(fresh.task_id), probe.key("rollback-input")
    actor, value = probe.actor(), request(probe, fresh.task_id, reference)
    try:
        with UnitOfWork(probe.pools.normal) as uow:
            result = bind_initial_input_in_uow(uow, actor, fresh.task_id, value, idempotency_key=rollback_key)
            require(result.status_code == 200, "engineering_uow_binding_failed")
            raise TaskCheckFailure("engineering_deliberate_rollback")
    except TaskCheckFailure as error:
        require(str(error) == "engineering_deliberate_rollback", "engineering_unexpected_uow_failure")
    require(probe.snapshot(fresh.task_id) == before and row(probe, fresh.task_id) is None,
            "engineering_uow_rollback_incomplete")
    with UnitOfWork(probe.pools.control) as uow:
        require(uow.connection.scalar(select(commands.c.command_id).where(
            commands.c.command_id == result.body.command_id,
        )) is None, "engineering_uow_command_leaked")


def test_invalidation_and_current_access(probe, reference, replay_data):
    task_id, value, key, first = replay_data
    current = probe.row(task_id)
    invalidation = InvalidateTaskInputRequest(
        expected_version=current["version"], expected_control_revision=current["control_revision"],
        expected_input_validity_revision=current["input_validity_revision"],
        change_ref=probe.declaration.source_ref, reason="test-only-input-change",
    )
    probe.app.invalidate_input(probe.actor(), task_id, invalidation, idempotency_key=probe.key("invalidate-initial"))
    require(bind(probe, task_id, value, key=key) == first, "engineering_historical_replay_changed")
    bind(probe, task_id, request(probe, task_id, reference), expected="input_not_current")
    actor = probe.actor()
    probe.maintenance.disable_user(DisableUserRequest(user_id=OWNER))
    try:
        probe.app.bind_initial_input(actor, task_id, value, idempotency_key=key)
    except IdentityError:
        pass
    else:
        raise TaskCheckFailure("engineering_revoked_replay_was_allowed")


def run_checks(fixture):
    probe = TaskProbe(fixture)
    scene = "engineering_input_fixture_setup_failed"
    try:
        probe.open()
        reference = input_ref(probe, "engineering-initial-input")
        scene = "engineering_input_binding_checks_failed"
        replay_data = test_bindings(probe, reference)
        scene = "engineering_input_rejection_checks_failed"
        test_rejections(probe, reference)
        scene = "engineering_input_transaction_checks_failed"
        test_source_and_rollback(probe, reference)
        scene = "engineering_input_current_access_checks_failed"
        test_invalidation_and_current_access(probe, reference, replay_data)
        with UnitOfWork(probe.maintenance_engine) as uow:
            require(uow.connection.scalar(select(func.count()).select_from(task_reference_records).where(
                task_reference_records.c.record_kind.in_(("candidate", "evidence", "human_conclusion")),
            )) == 0, "engineering_binding_created_completion_facts")
        return {"draft_and_active_initial_binding": True, "exact_declared_inputs_required": True,
                "missing_replaced_extra_and_unregistered_inputs_rejected": True,
                "version_control_and_input_gates": True, "cancellation_and_invalidation_closed": True,
                "stable_success_and_rejection_replays": True, "current_identity_before_replay": True,
                "caller_uow_rollback": True, "no_candidate_or_acceptance_fact_created": True}
    except TaskCheckFailure:
        raise
    except Exception:
        raise TaskCheckFailure(scene) from None
    finally:
        probe.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=55435)
    args = parser.parse_args()
    report = {"method_revision": METHOD_REVISION, "mode": "development_worktree",
              "started_at_utc": datetime.now(UTC).isoformat(), "complete_scope": False,
              "scope": "registered test metadata and initial binding; no real source, candidate or acceptance chain"}
    try:
        with database_fixture(port=args.port) as fixture:
            report["fixture_id"] = fixture.project_name
            report["checks"] = run_checks(fixture)
        report.update(status="passed", cleanup="complete")
    except (TaskCheckFailure, DatabaseFixtureError) as error:
        report.update(status="failed", failure_code=str(error))
    except Exception:
        report.update(status="failed", failure_code="engineering_input_verifier_failed")
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
