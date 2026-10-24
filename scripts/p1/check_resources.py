"""One focused real-PostgreSQL/SQLite/cgroup method for P1.3-01, not product acceptance."""

import argparse
import json
import multiprocessing
import os
import platform
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, text

from database.commands import CommandConflict
from database.connection import create_engine_from_settings
from database.models import load_business_metadata
from database.uow import UnitOfWork
from modules.execution.application import ResourceApplication
from modules.execution.commands import reserve_in_uow
from modules.execution.dispatch import ResourceDispatcher
from modules.execution.errors import ResourceError
from modules.execution.registry import register_pool_in_uow, register_runner_in_uow
from modules.execution.tables import resource_reservations
from packages.contracts.p1.task_requests import CancelTaskRequest
from scripts.p1.resource_fixture import (
    ARGV, accept_in_process, counts, pool_and_runners, reject, request_for, require, subject,
)
from scripts.p1.resource_inputs import METHOD, snapshot
from scripts.p1.resource_physical import run_physical
from scripts.p1.task_probe import TaskProbe


def structure(probe, worker, pool, registrations):
    with UnitOfWork(probe.maintenance_engine) as uow:
        register_pool_in_uow(uow, pool)
        for registration in registrations:
            register_runner_in_uow(uow, registration)
        clone = pool.model_copy(update={"pool": pool.pool.model_copy(update={"host_resource_pool_id": "second-copy"})})
        reject(lambda: register_pool_in_uow(uow, clone), ValueError, "physical_host_pool_already_registered")
        context = MigrationContext.configure(uow.connection, opts={
            "include_schemas": True, "include_name": lambda name, kind, parent: kind != "schema" or name == "cloudhelm",
            "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table" or name.startswith("resource_"),
        })
        require(not compare_metadata(context, load_business_metadata()), "resource_metadata_migration_drift")
    with UnitOfWork(worker) as uow:
        require(not uow.connection.scalar(text("SELECT has_table_privilege(current_user, 'cloudhelm.resource_pools', 'INSERT')")),
                "resource_worker_can_register_host_capacity")
        require(not uow.connection.scalar(text("SELECT has_column_privilege(current_user, 'cloudhelm.resource_pools', 'registration_json', 'UPDATE')")),
                "resource_worker_can_change_host_capacity")
    return {"single_pool_per_host": True, "linear_migration_matches_metadata": True, "maintenance_only_registration": True}


def concurrent_admission(application, subjects, registrations):
    barrier = Barrier(2)
    requests = [request_for(task, registration) for (_, task), registration in zip(subjects, registrations)]

    def submit(index):
        actor, task = subjects[index]
        barrier.wait(timeout=5)
        try:
            result = application.reserve(actor, task.task_id, requests[index], idempotency_key="resource-race")
            return index, result
        except ResourceError as error:
            require(error.code == "shared_host_capacity_exceeded", "resource_concurrent_wrong_rejection")
            return index, None

    before = counts(application.engine)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, (0, 1)))
    accepted = [(index, result) for index, result in results if result is not None]
    require(len(accepted) == 1, "resource_shared_pool_double_admission")
    require(counts(application.engine) == tuple(value + 1 for value in before), "resource_admission_not_atomic_with_command_event_outbox")
    index, result = accepted[0]
    actor, task = subjects[index]
    request = requests[index]
    replay = application.reserve(actor, task.task_id, request, idempotency_key="resource-race")
    require(replay == result, "resource_replay_changed_acceptance")
    changed = request.model_copy(update={"expires_at_utc": request.expires_at_utc + timedelta(seconds=1)})
    reject(lambda: application.reserve(actor, task.task_id, changed, idempotency_key="resource-race"), CommandConflict)
    return index, request, {"two_users_projects_and_runners_shared_one_pool": True,
                            "concurrent_admissions": 1, "atomic_command_reservation_event_outbox": True,
                            "same_identity_replays_original_result": True, "changed_digest_rejected": True}


def local_confirmation(application, worker_app, pool, registration, request, other_registration, other_request):
    ledger_module = import_module("services.dev-runner.resource_ledger")
    runtime = import_module("services.dev-runner.resource_runtime")
    limits = import_module("services.dev-runner.resource_limits")
    boundary = limits.DockerScratchBoundary(registration, ARGV)
    runner = runtime.ResourceRunner(ledger_module.ResourceLedger(pool, registration), boundary)
    # Two actual processes deliver the same message. Neither response is handed
    # to Hub; a new executor instance recovers the receipt from SQLite.
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [context.Process(target=accept_in_process, args=(pool, registration, request.resources, queue)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        values = [queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=5)
        require(values == ["accepted", "accepted"] and all(process.exitcode == 0 for process in processes),
                "resource_cross_process_duplicate_delivery_failed")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
    runner = runtime.ResourceRunner(ledger_module.ResourceLedger(pool, registration), boundary)
    dispatcher = ResourceDispatcher(worker_app, runner)
    restored = dispatcher.reconcile(request.resources.identity.reservation_id)
    require(restored.state == "reserved", "resource_lost_receipt_not_recovered")
    with runner.ledger.locked() as db:
        require(db.execute("SELECT count(*) FROM allocations").fetchone()[0] == 1, "resource_duplicate_created_second_local_allocation")
    other = runtime.ResourceRunner(ledger_module.ResourceLedger(pool, other_registration),
                                   limits.DockerScratchBoundary(other_registration, ARGV))
    refused = other.accept(other_request.resources, backend=other_registration.backend)
    require(refused.state == "closed_unstarted" and refused.disk_reclaimed,
            "resource_local_other_runner_bypassed_shared_capacity")
    changed = request.resources.model_copy(update={"request_digest": "sha256:" + "1" * 64})
    reject(lambda: runner.accept(changed, backend=registration.backend), ValueError, "resource_request_digest_mismatch")
    return runner, dispatcher, {"two_processes_one_durable_acceptance": True, "lost_receipt_restored_after_reopen": True,
                                "other_runner_cannot_duplicate_host_capacity": True, "altered_request_digest_rejected": True}


def final_gates(probe, application, worker_app, subjects, registrations, pool, runner):
    actor, task = subjects[0]
    request = request_for(task, registrations[0])
    before = counts(application.engine)
    try:
        with UnitOfWork(application.engine) as uow:
            reserve_in_uow(uow, actor, task.task_id, request, idempotency_key="rollback-resource")
            raise InterruptedError()
    except InterruptedError:
        pass
    require(counts(application.engine) == before, "resource_caller_rollback_left_partial_writes")
    expired = request.model_copy(update={"expires_at_utc": datetime.now(UTC) - timedelta(seconds=1)})
    reject(lambda: application.reserve(actor, task.task_id, expired, idempotency_key="expired-resource"), ResourceError,
           "resource_request_expired")
    mismatch = request_for(task, registrations[0].model_copy(update={"cpu_period_us": 200000}))
    reject(lambda: application.reserve(actor, task.task_id, mismatch, idempotency_key="wrong-capability"), ResourceError,
           "resource_runner_identity_or_capability_mismatch")
    application.reserve(actor, task.task_id, request, idempotency_key="close-before-start")
    runtime = import_module("services.dev-runner.resource_runtime")
    ledger = import_module("services.dev-runner.resource_ledger")
    limits = import_module("services.dev-runner.resource_limits")
    other = runtime.ResourceRunner(ledger.ResourceLedger(pool, registrations[0]), limits.DockerScratchBoundary(registrations[0], ARGV))
    dispatcher = ResourceDispatcher(worker_app, other)
    dispatcher.deliver(request.resources.identity.reservation_id)
    canceled = probe.app.cancel(actor, task.task_id, CancelTaskRequest(expected_version=task.version,
        expected_control_revision=task.control_revision, cancel_reason="resource-start-gate-check"),
        idempotency_key="cancel-before-resource-start")
    require(canceled.status_code == 202, "resource_task_cancel_failed")
    closed = dispatcher.start(request.resources.identity.reservation_id)
    require(closed.state == "released", "resource_stale_start_not_durably_closed")
    repeated = dispatcher.start(request.resources.identity.reservation_id)
    require(repeated == closed and other.query(request.resources.identity.reservation_id).state == "closed_unstarted",
            "resource_late_delivery_reopened_start_fence")
    return {"caller_rollback_removes_all_four_records": True, "expired_and_unmatched_runner_rejected": True,
            "current_task_cancel_closes_unstarted_allocation": True, "late_start_stays_fenced": True}


def run(port, report):
    fixture_module = import_module("scripts.p1.database_fixture")
    fixture_module._RUNTIME_ROOT = Path("/root/.local/state/cloudhelm/p1-resource-fixtures")
    original_remove = fixture_module._remove_runtime
    safe = {"confirmed": True}

    def guarded_remove(path):
        if safe["confirmed"]:
            original_remove(path)
        else:
            report["private_fixture_retained_for_reconciliation"] = True

    fixture_module._remove_runtime = guarded_remove
    try:
        _run_fixture(fixture_module, port, report, safe)
    finally:
        fixture_module._remove_runtime = original_remove


def _run_fixture(fixture_module, port, report, safe):
    ledger_module = import_module("services.dev-runner.resource_ledger")
    with fixture_module.database_fixture(port=port) as fixture:
        ledger_module.ROOT = fixture.runtime_dir / "host-ledger"
        probe, worker = TaskProbe(fixture), None
        runner = dispatcher = request = None
        try:
            probe.open()
            worker = create_engine_from_settings(fixture.settings("worker"), purpose="control")
            application = ResourceApplication(probe.pools.normal, probe.pools.control)
            worker_app = ResourceApplication(worker, worker)
            pool, registrations = pool_and_runners()
            report["structure"] = structure(probe, worker, pool, registrations)
            subjects = [subject(fixture, probe, name) for name in ("a", "b")]
            index, request, report["admission"] = concurrent_admission(application, subjects, registrations)
            report["operation"] = {"identity": request.resources.identity.model_dump(mode="json"),
                "creation_request_digest": request.resources.request_digest,
                "image_id": registrations[index].image_id}
            other_index = 1 - index
            runner, dispatcher, report["local_confirmation"] = local_confirmation(application, worker_app, pool, registrations[index], request,
                registrations[other_index], request_for(subjects[other_index][1], registrations[other_index]))
            safe["confirmed"] = False
            report["physical"] = run_physical(application, dispatcher, runner, request, subjects[index][0])
            report["gates"] = final_gates(probe, application, worker_app, subjects, registrations, pool, runner)
            with UnitOfWork(worker) as uow:
                allocations = uow.connection.scalars(select(resource_reservations.c.allocation_json)).all()
            require(all(value["state"] == "released" for value in allocations), "resource_final_charge_not_zero")
            report["remaining_accounted_allocations"] = 0
        finally:
            try:
                if runner is not None and request is not None:
                    runner.stop(request.resources.identity.reservation_id)
                    fact = runner.query(request.resources.identity.reservation_id)
                    safe["confirmed"] = fact.disk_reclaimed
                    require(safe["confirmed"], "resource_cleanup_unconfirmed")
            finally:
                if worker is not None:
                    worker.dispose()
                probe.close()
    report["database_and_private_fixture_cleanup"] = "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=55446)
    parser.add_argument("--inputs", action="store_true")
    arguments = parser.parse_args()
    inputs = snapshot()
    if arguments.inputs:
        print(json.dumps(inputs, ensure_ascii=False, indent=2))
        return 0
    report = {"method_revision": METHOD, "status": "failed", "started_at_utc": datetime.now(UTC).isoformat(),
              "source_tree_digest": inputs["source_tree_digest"], "input_file_count": inputs["file_count"],
              "environment": "WSL Ubuntu-24.04 Linux/amd64; root maintenance; PostgreSQL 16.13; cgroup v2/systemd; Docker 29.1.3",
              "human_acceptance": None, "independent_machine_acceptance": None}
    try:
        require(os.geteuid() == 0 and os.environ.get("WSL_DISTRO_NAME") == "Ubuntu-24.04", "resource_root_wsl_method_required")
        boundary_api = import_module("services.dev-runner.artifact_environment_docker")
        report["observed_environment"] = {"kernel": platform.release(), "python": platform.python_version(),
            "machine": platform.machine(), "controller_uid": os.geteuid(),
            "docker_version": boundary_api.engine("GET", "/version")["Version"]}
        run(arguments.port, report)
        require(snapshot() == inputs, "resource_public_inputs_changed_during_method")
        report.update(status="passed", public_inputs_unchanged=True)
    except Exception as failure:
        report["failure_type"] = type(failure).__name__
        if type(failure) in {ValueError, AssertionError} or type(failure).__name__ == "ProbeFailure":
            report["failure_code"] = str(failure)
        report["failure_locations"] = [f"{Path(frame.filename).name}:{frame.lineno}" for frame in traceback.extract_tb(failure.__traceback__)[-5:]]
        cause = failure
        for _ in range(8):
            original = getattr(cause, "orig", None)
            if original is not None and getattr(original, "sqlstate", None):
                diagnostic = getattr(original, "diag", None)
                report["database_failure_category"] = {"sqlstate": original.sqlstate,
                    "table": getattr(diagnostic, "table_name", None), "constraint": getattr(diagnostic, "constraint_name", None)}
                break
            cause = cause.__context__
            if cause is None:
                break
    report["ended_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
