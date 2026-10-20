"""Verify real Workspace/Build intents block and later settle Task completion/cancellation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import sys
import time
import traceback
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from sqlalchemy import func, select

from database.commands import commands
from database.uow import UnitOfWork
from modules.collaboration.tables import task_completion_reports
from modules.sync.tables import event_log, outbox
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import CONTROL_WORKFLOW
from packages.contracts.p1.build_records import BuildView
from packages.contracts.p1.build_requests import BuildCommandResult, RequestBuildRequest
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.task_requests import CancelTaskRequest, CompleteTaskRequest, ReconcileTaskRequest
from packages.contracts.p1.task_results import TaskView
from packages.contracts.p1.workspace_git import WorkspaceFile, content_digest
from packages.contracts.p1.workspace_requests import MutateWorkspaceFileRequest, WorkspaceCommandResult, WorkspaceView
from packages.contracts.p1.workspace_uploads import WorkspaceMutationUpload
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture
from scripts.p1.engineering_chain import (
    accept_source, freeze_candidate, grant_engineering, materialize, mutate, reference_task, workspace_guard,
)
from scripts.p1.engineering_fixture import (
    EngineeringCheckFailure, EngineeringProbe,
    ROOT, fixed_inputs, process_fixture, require,
)
from scripts.p1.engineering_physical import candidate_files
from scripts.p1.engineering_task_fixture import (
    METHOD_REVISION, PROTOCOL_CLASSIFICATION, apply_workspace_operation_without_hub_receipt,
    close_build_unstarted_after_cancel, control_facts, execute_build_without_hub_receipt,
    refresh_protocol_work_items, stage_protocol_completion, task_application, task_control_worker_running,
)
from scripts.p1.runtime_processes import _ACTIVE, api_running, worker_running

CASE_NAMES = ("workspace_complete", "workspace_cancel", "build_complete", "build_cancel")
SETTLED_BUILD_CLOSURES = {"closed_unstarted", "ended_reconciled", "safely_stopped"}


def _environment():
    require(os.name == "posix" and os.environ.get("WSL_DISTRO_NAME") == "Ubuntu-24.04"
            and os.getuid() == 1000 and ROOT == Path("/mnt/e/Project/CloudHelm"),
            "engineering_task_control_requires_registered_wsl_checkout")
    return {"distribution": "Ubuntu-24.04", "kernel": platform.release(), "uid": os.getuid(),
            "repository": str(ROOT), "mount_namespace": os.readlink("/proc/self/ns/mnt"),
            "python": platform.python_version(), "dbos": version("dbos"),
            "sqlalchemy": version("sqlalchemy"), "interpreter": sys.executable}


def _wait_workflow(probe, workflow_id: str, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = probe.workflow_status(workflow_id)
        if status == "SUCCESS":
            return status
        require(status not in {"ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"},
                "engineering_task_control_workflow_failed")
        time.sleep(0.2)
    raise EngineeringCheckFailure("engineering_task_control_workflow_timeout")


def _task_workflow_handoff(probe, result):
    """Confirm Task command, event, outbox and DBOS binding from independent reads."""
    with UnitOfWork(probe.pools.control) as uow:
        command = uow.connection.execute(select(
            commands.c.status_code, commands.c.request_digest, commands.c.result_json,
        ).where(commands.c.command_id == result.body.command_id)).mappings().one_or_none()
        bindings = uow.connection.execute(select(workflow_bindings).where(
            workflow_bindings.c.command_id == result.body.command_id,
        )).mappings().all()
        event_count = uow.connection.scalar(select(func.count()).select_from(event_log).where(
            event_log.c.command_id == result.body.command_id,
        ))
        outbox_count = uow.connection.scalar(select(func.count()).select_from(outbox.join(event_log)).where(
            event_log.c.command_id == result.body.command_id,
        ))
    require(command is not None and command["status_code"] == result.status_code
            and command["result_json"] == result.body.model_dump(mode="json")
            and len(bindings) == 1 and event_count >= 1 and outbox_count == event_count,
            "engineering_task_control_workflow_handoff_missing")
    binding = bindings[0]
    require(binding["workflow_id"] == result.body.workflow_id
            and binding["business_kind"] == "task" and binding["business_id"] == result.body.task_id
            and binding["workflow_name"] == CONTROL_WORKFLOW and binding["queue_name"] == "control"
            and binding["request_digest"] == command["request_digest"],
            "engineering_task_control_workflow_binding_mismatch")
    status = probe.workflow_status(binding["workflow_id"])
    require(status is not None, "engineering_task_control_workflow_not_enqueued")
    return {"command_id": result.body.command_id, "workflow_id": binding["workflow_id"],
            "workflow_name": binding["workflow_name"], "queue_name": binding["queue_name"],
            "event_count": event_count, "outbox_count": outbox_count,
            "dbos_status_after_acceptance": status}


def _case_setup(probe, storage_ref, source, source_workflow):
    cases = {}
    with worker_running(probe.fixture):
        for name in CASE_NAMES:
            active, input_ref = reference_task(probe, source, source_workflow)
            workspace_id, manifest, _, _ = materialize(probe, active, input_ref)
            manifest, _ = mutate(probe, workspace_id, input_ref, manifest,
                                 "Fixed candidate for Task control protocol validation.\n")
            candidate = freeze_candidate(probe, workspace_id, input_ref, manifest)
            require(candidate.snapshot.binding.task_id == active.task_id,
                    "engineering_task_control_candidate_task_mismatch")
            cases[name] = {"name": name, "task_id": active.task_id, "input_ref": input_ref,
                           "workspace_id": workspace_id, "candidate": candidate,
                           "physical_candidate_id": candidate.snapshot.candidate_id}
    return cases


def _workspace_intent(probe, case):
    task_id, workspace_id, input_ref = case["task_id"], case["workspace_id"], case["input_ref"]
    view = probe.get(f"/api/workspaces/{workspace_id}", WorkspaceView)
    raw = f"Pending operation for {case['name']}.\n"
    content = raw.encode("utf-8")
    path = f"cloudhelm-{case['name']}.txt"
    request = MutateWorkspaceFileRequest(
        **workspace_guard(view, input_ref),
        action="write", path=path, expected_manifest_digest=case["candidate"].snapshot.manifest_digest,
        expected_file=None,
        replacement=WorkspaceFile(path=path, mode="100644", size_bytes=len(content),
                                  content_digest=content_digest(content)),
    )
    upload = WorkspaceMutationUpload(request=request, content_utf8=raw)
    accepted = probe.post(f"/api/workspaces/{workspace_id}/files", {
        "request": request.model_dump(mode="json"), "content_utf8": upload.content_utf8,
    }, WorkspaceCommandResult, expected=202, key=probe.key(case["name"]))
    require(accepted.task_id == task_id and accepted.outcome == "accepted" and accepted.operation_id,
            "engineering_task_control_workspace_command_not_accepted")
    workflow_id = probe.handoff(accepted)
    case.update(operation_kind="workspace", operation_id=accepted.operation_id,
                operation_command_id=accepted.command_id, engineering_workflow_id=workflow_id,
                operation_intent=accepted.model_dump(mode="json"))
    return accepted


def _build_intent(probe, storage_ref, case):
    task_id = case["task_id"]
    view = probe.get(f"/api/tasks/{task_id}", TaskView)
    files, _ = candidate_files(storage_ref, case["candidate"])
    definition = importlib.import_module("services.dev-runner.engineering_definition").definition_for_candidate(
        files, view.declaration.acceptance_assets_ref,
    )
    result = probe.post(f"/api/tasks/{task_id}/builds", RequestBuildRequest(
        expected_version=view.version, expected_control_revision=view.control_revision,
        expected_input_validity_revision=view.input_validity_revision,
        candidate_id=case["physical_candidate_id"], input_set_ref=case["input_ref"], definition=definition,
    ), BuildCommandResult, expected=202, key=probe.key(case["name"]))
    require(result.task_id == task_id and result.outcome == "accepted" and result.operation_id,
            "engineering_task_control_build_command_not_accepted")
    workflow_id = probe.handoff(result)
    case.update(operation_kind="build", operation_id=result.operation_id,
                operation_command_id=result.command_id, engineering_workflow_id=workflow_id,
                operation_intent=result.model_dump(mode="json"), definition=definition)
    return result


def _assert_hub_receipt_pending(probe, case):
    if case["operation_kind"] == "workspace":
        from modules.workspaces.queries import WorkspaceOperationView

        value = probe.get(
            f"/api/workspaces/{case['workspace_id']}/operations/{case['operation_id']}",
            WorkspaceOperationView,
        )
        require(value.state == "accepted" and value.registration is None,
                "engineering_task_control_workspace_pending_receipt_not_retained")
        case["hub_pending"] = {"state": value.state, "receipt_registered": False}
    else:
        value = probe.get(f"/api/tasks/{case['task_id']}/builds/{case['operation_id']}", BuildView)
        require(value.state == "accepted" and value.execution is None and not value.content_verified,
                "engineering_task_control_build_pending_receipt_not_retained")
        case["hub_pending"] = {"state": value.state, "receipt_registered": False}


def _cancel(probe, actor, app, case):
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    result = app.cancel(actor, case["task_id"], CancelTaskRequest(
        expected_version=view.version, expected_control_revision=view.control_revision,
        cancel_reason="p1_2_engineering_operation_pending",
    ), idempotency_key=probe.key(case["name"] + "-cancel"))
    require(result.status_code == 202 and result.body.outcome == "cancellation_requested"
            and result.body.control_purpose == "cancellation" and result.body.workflow_id,
            "engineering_task_control_cancel_not_accepted")
    case["cancel_command_id"], case["cancel_workflow_id"] = result.body.command_id, result.body.workflow_id
    case["cancel_acceptance"] = result.body.model_dump(mode="json")
    case["task_workflow_handoff"] = _task_workflow_handoff(probe, result)
    return result


def _assert_pending_completion(probe, actor, app, case, fixture):
    snapshot = control_facts(probe, case["task_id"])
    facts = snapshot.facts
    require(facts.input_current and facts.required_work_items_accepted
            and facts.required_acceptance_satisfied and facts.evidence_current
            and facts.required_waits_satisfied and facts.operation_set_current,
            "engineering_task_control_non_operation_gates_not_ready")
    blockers = {(item.code, item.object_id) for item in snapshot.blockers}
    require(blockers == {("writes_unsettled", case["operation_id"])},
            "engineering_task_control_pending_blocker_classification_mismatch")
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    result = app.complete(actor, case["task_id"], CompleteTaskRequest(
        expected_version=view.version, expected_control_revision=view.control_revision,
        expected_input_validity_revision=view.input_validity_revision,
    ), idempotency_key=probe.key(case["name"] + "-blocked-complete"))
    require(result.status_code == 409 and result.body.code == "writes_unsettled",
            "engineering_task_control_completion_did_not_block_pending_write")
    blockers = {item.object_id for item in result.body.blockers if item.code == "writes_unsettled"}
    require(blockers == {case["operation_id"]}, "engineering_task_control_completion_operation_id_hidden")
    with UnitOfWork(probe.pools.control) as uow:
        count = uow.connection.scalar(select(func.count()).select_from(task_completion_reports).where(
            task_completion_reports.c.task_id == case["task_id"],
        ))
    require(count == 0, "engineering_task_control_pending_write_created_report")
    case["protocol_completion_fixture"] = {
        "classification": fixture.classification, "input_set_ref": fixture.input_set_ref.model_dump(mode="json"),
        "candidate_ref": fixture.candidate_ref.model_dump(mode="json"),
        "environment_ref": fixture.environment_ref.model_dump(mode="json"),
        "evidence_refs": [ref.model_dump(mode="json") for ref in fixture.evidence_refs],
    }
    case["completion_block"] = {
        "status_code": result.status_code, "code": result.body.code,
        "operation_id": case["operation_id"], "report_count": count,
        "all_non_operation_gates_ready": True,
    }


def _wait_workspace(probe, case):
    from modules.workspaces.queries import WorkspaceOperationView

    value = probe.wait(
        f"/api/workspaces/{case['workspace_id']}/operations/{case['operation_id']}",
        WorkspaceOperationView, lambda item: item.state == "registered",
        workflow_id=case["engineering_workflow_id"], timeout=60,
    )
    require(value.registration is not None and value.registration.receipt.operation_id == case["operation_id"],
            "engineering_task_control_workspace_receipt_missing")
    case["terminal"] = {"state": value.state, "physical_outcome": value.registration.receipt.outcome,
                         "applicable": value.registration.applicable,
                         "receipt_operation_id": value.registration.receipt.operation_id}


def _wait_build(probe, case):
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        view = probe.get(f"/api/tasks/{case['task_id']}/builds/{case['operation_id']}", BuildView)
        status = probe.workflow_status(case["engineering_workflow_id"])
        require(status not in {"ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"},
                "engineering_task_control_build_workflow_failed")
        if view.state in {"succeeded", "failed"} and view.execution is not None:
            observation = view.execution.observation
            require(observation.closure in SETTLED_BUILD_CLOSURES,
                    "engineering_task_control_build_receipt_not_terminal")
            if view.state == "succeeded":
                require(view.content_verified and observation.closure == "ended_reconciled"
                        and observation.exit_code == 0, "engineering_task_control_build_success_unverified")
            if status != "SUCCESS":
                time.sleep(0.2)
                continue
            case["terminal"] = {"state": view.state, "closure": observation.closure,
                                "exit_code": observation.exit_code,
                                "content_verified": view.content_verified,
                                "applicable": view.execution.applicable}
            return
        require(view.state != "unknown", "engineering_task_control_build_result_unknown")
        time.sleep(0.5)
    raise EngineeringCheckFailure("engineering_task_control_build_receipt_timeout")


def _assert_cancel_workflow(probe, app, case):
    _wait_workflow(probe, case["cancel_workflow_id"])
    result = app.run_control(case["cancel_command_id"])
    require(result.outcome == "blocked" and result.code == "cancellation_physical_execution_unsettled",
            "engineering_task_control_cancel_workflow_did_not_wait_for_physical_receipt")
    ids = {blocker.object_id for blocker in result.blockers if blocker.object_id is not None}
    require(ids == {case["operation_id"]}, "engineering_task_control_cancel_operation_id_hidden")
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    require(view.state == "active" and view.ordinary_progress_closed and view.cancellation is not None
            and view.completion_report_id is None, "engineering_task_control_cancelled_before_receipt")
    case["control_wait"] = {"workflow_status": "SUCCESS", "outcome": result.outcome,
                            "code": result.code, "operation_id": case["operation_id"],
                            "command_id": case["cancel_command_id"],
                            "workflow_id": case["cancel_workflow_id"],
                            "state_before_receipt": view.state, "ordinary_progress_closed": True}


def _finish_cancel(probe, actor, app, case):
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    require(view.state == "active" and view.cancellation is not None and not view.blockers,
            "engineering_task_control_receipt_did_not_clear_cancellation_blocker")
    result = app.reconcile(actor, case["task_id"], ReconcileTaskRequest(
        expected_version=view.version, expected_control_revision=view.control_revision, purpose="cancellation",
    ), idempotency_key=probe.key(case["name"] + "-cancel-reconcile"))
    require(result.status_code == 202 and result.body.workflow_id,
            "engineering_task_control_cancel_reconcile_not_accepted")
    case["reconcile_handoff"] = _task_workflow_handoff(probe, result)
    _wait_workflow(probe, result.body.workflow_id)
    applied = app.run_control(result.body.command_id)
    require(applied.outcome == "cancelled" and applied.state == "cancelled",
            "engineering_task_control_cancel_did_not_finish_after_receipt")
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    require(view.state == "cancelled" and view.ordinary_progress_closed and view.completion_report_id is None,
            "engineering_task_control_cancel_terminal_projection_mismatch")
    case["final"] = {"state": view.state, "outcome": applied.outcome,
                     "reconcile_workflow_id": result.body.workflow_id}


def _finish_completion(probe, actor, app, case, fixture):
    refresh_protocol_work_items(probe, fixture, label=case["name"] + "-post-receipt")
    snapshot = control_facts(probe, case["task_id"])
    require(not snapshot.blockers and snapshot.facts.input_current and snapshot.facts.evidence_current
            and snapshot.facts.required_work_items_accepted and snapshot.facts.required_acceptance_satisfied,
            "engineering_task_control_no_pending_completion_gates_not_ready")
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    result = app.complete(actor, case["task_id"], CompleteTaskRequest(
        expected_version=view.version, expected_control_revision=view.control_revision,
        expected_input_validity_revision=view.input_validity_revision,
    ), idempotency_key=probe.key(case["name"] + "-complete-after-receipt"))
    require(result.status_code == 200 and result.body.outcome == "completed",
            "engineering_task_control_completion_failed_after_receipt")
    report = app.report(actor, case["task_id"])
    case["final"] = {"state": result.body.state, "outcome": result.body.outcome,
                     "completion_report_id": report.report_id,
                     "protocol_validation_input": fixture.classification}


def _project_status(probe, case):
    view = probe.get(f"/api/tasks/{case['task_id']}", TaskView)
    return {"state": view.state, "ordinary_progress_closed": view.ordinary_progress_closed,
            "completion_report_id": view.completion_report_id,
            "operation_id": case["operation_id"], "terminal": case["terminal"]}


def _run_cases(probe, storage_ref, runtime, cases, report):
    actor, app = task_application(probe)
    complete_fixtures = {}
    for name in CASE_NAMES:
        case = cases[name]
        if name.startswith("workspace"):
            accepted = _workspace_intent(probe, case)
            case["physical"] = apply_workspace_operation_without_hub_receipt(runtime, accepted.operation_id)
        else:
            accepted = _build_intent(probe, storage_ref, case)
            if name == "build_cancel":
                cancel_result, physical = close_build_unstarted_after_cancel(
                    runtime, accepted.operation_id, lambda: _cancel(probe, actor, app, case),
                )
                case["cancel_command_id"] = cancel_result.body.command_id
                case["cancel_workflow_id"] = cancel_result.body.workflow_id
                case["cancel_acceptance"] = cancel_result.body.model_dump(mode="json")
                case["physical"] = physical
            else:
                case["physical"] = execute_build_without_hub_receipt(runtime, accepted.operation_id)
        if name.endswith("complete"):
            fixture = stage_protocol_completion(probe, case["task_id"], label=name)
            _assert_pending_completion(probe, actor, app, case, fixture)
            complete_fixtures[name] = fixture
        elif name == "workspace_cancel":
            _cancel(probe, actor, app, case)
        _assert_hub_receipt_pending(probe, case)

    report["case_acceptance"] = [{"name": name, "task_id": cases[name]["task_id"],
                                  "operation_kind": cases[name]["operation_kind"],
                                  "operation_id": cases[name]["operation_id"],
                                  "operation_command_id": cases[name]["operation_command_id"],
                                  "engineering_workflow_id": cases[name]["engineering_workflow_id"],
                                  "hub_pending": cases[name]["hub_pending"],
                                  "physical": cases[name]["physical"]} for name in CASE_NAMES]
    target_commands = {cases[name]["operation_command_id"] for name in CASE_NAMES}
    handoffs = [item for item in probe.evidence["workflow_handoffs"]
                if item["command_id"] in target_commands]
    require(len(handoffs) == len(CASE_NAMES), "engineering_task_control_engineering_handoffs_missing")
    report["same_uow_engineering_handoffs"] = handoffs

    with task_control_worker_running(probe.fixture):
        for name in ("workspace_cancel", "build_cancel"):
            _assert_cancel_workflow(probe, app, cases[name])
    report["execution_barrier"] = {
        "task_only_queues": ["control", "orchestration"],
        "engineering_queue_polled": False,
        "cancel_workflows_returned_before_engineering_receipts": True,
        "operation_receipts_registered_by_full_worker_afterward": True,
    }
    with worker_running(probe.fixture):
        for name in CASE_NAMES:
            case = cases[name]
            if case["operation_kind"] == "workspace":
                _wait_workspace(probe, case)
            else:
                _wait_build(probe, case)
        for name in CASE_NAMES:
            case = cases[name]
            if name.endswith("complete"):
                _finish_completion(probe, actor, app, case, complete_fixtures[name])
            else:
                _finish_cancel(probe, actor, app, case)
            case["final_projection"] = _project_status(probe, case)

    report["cases"] = [{"name": name, "task_id": cases[name]["task_id"],
                         "operation_kind": cases[name]["operation_kind"],
                         "operation_id": cases[name]["operation_id"],
                         "operation_command_id": cases[name]["operation_command_id"],
                         "engineering_workflow_id": cases[name]["engineering_workflow_id"],
                         "hub_pending": cases[name]["hub_pending"],
                         "physical": cases[name]["physical"],
                         "task_workflow_handoff": cases[name].get("task_workflow_handoff"),
                         "reconcile_handoff": cases[name].get("reconcile_handoff"),
                         "completion_block": cases[name].get("completion_block"),
                         "control_wait": cases[name].get("control_wait"),
                         "terminal": cases[name]["terminal"], "final": cases[name]["final"],
                         "final_projection": cases[name]["final_projection"]} for name in CASE_NAMES]


def run(args, report):
    report["environment"] = _environment()
    storage_ref = DevelopmentStorageRef(storage_id=args.storage_id,
                                        instance_revision=args.storage_revision, purpose="workspace")
    storage_api = importlib.import_module("services.dev-runner.development_storage")
    with storage_api.DevelopmentStorage(storage_ref.storage_id).admit_ref(storage_ref, requested_bytes=0) as admitted:
        report["storage_before"] = admitted.observe().model_dump(mode="json")
    probe = fixture = runtime = None
    try:
        with database_fixture(port=args.port) as fixture:
            report["database_fixture"] = {"project_name": fixture.project_name, "port": fixture.port,
                                           "installation_id": fixture.baseline.installation_id,
                                           "isolated_new_database": True}
            try:
                probe = EngineeringProbe(process_fixture(fixture, storage_ref))
                probe.open()
                with api_running(probe.fixture, instance="taskctl") as api:
                    probe.http = api.client
                    grant_engineering(probe)
                    source, source_workflow = accept_source(probe)
                    cases = _case_setup(probe, storage_ref, source, source_workflow)
                    registry_module = importlib.import_module("services.dev-runner.engineering_registry")
                    runtime_module = importlib.import_module("services.hub-worker.engineering_runtime")
                    registration = registry_module.EngineeringRegistration(storage=storage_ref)
                    registry = registry_module.EngineeringRegistry(registration)
                    runtime = runtime_module.EngineeringRuntime(probe.pools.normal, probe.pools.control, registry)
                    _run_cases(probe, storage_ref, runtime, cases, report)
            finally:
                try:
                    if runtime is not None:
                        runtime.close()
                finally:
                    if probe is not None:
                        probe.close()
    finally:
        # The database fixture removes this private directory only after Docker
        # down succeeds; process registrations remain until their stop is known.
        if (fixture is not None and not fixture.runtime_dir.exists()
                and not _ACTIVE.get(fixture.project_name)):
            report["database_and_process_cleanup"] = "complete"
    with storage_api.DevelopmentStorage(storage_ref.storage_id).admit_ref(storage_ref, requested_bytes=0) as admitted:
        report["storage_after"] = admitted.observe().model_dump(mode="json")


def _public_input(value):
    return {key: item for key, item in value.items() if key != "files"}


def _task_control_worker_main():
    """Test worker mode: actual Task workflows only; engineering remains queued."""
    import signal
    import threading

    from dbos import DBOS, DBOSClient, DBOSConfig, DBOSPortableJSONSerializer
    from database.connection import create_business_pools, create_engine_from_settings
    from database.readiness import assert_runtime_ready
    from database.settings import load_database_settings
    from database.uow import UnitOfWork
    from modules.collaboration.application import TaskApplication
    from modules.collaboration.workflows import register_task_workflows
    from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION, DBOS_SCHEMA
    runtime = importlib.import_module("services.hub-worker.runtime")
    acquire_worker_process_lock = importlib.import_module(
        "services.hub-worker.process_lock",
    ).acquire_worker_process_lock
    stop, pools, client, system_engine = threading.Event(), None, None, None
    attempted, result = False, 1
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    try:
        runtime._local_environment()
        settings = load_database_settings("worker")
        pools = create_business_pools(settings)
        with UnitOfWork(pools.control) as uow:
            baseline = assert_runtime_ready(uow.connection, role="worker")
        acquire_worker_process_lock(baseline.installation_id)
        with UnitOfWork(pools.control) as uow:
            require(assert_runtime_ready(uow.connection, role="worker") == baseline,
                    "task_control_worker_installation_changed")
        client = DBOSClient(
            system_database_engine=pools.normal, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False,
            system_database_polling_concurrency=1, observability_query_timeout_sec=5,
        )
        system_engine = create_engine_from_settings(settings, purpose="dbos")
        application = TaskApplication(pools.normal, pools.control, client)
        attempted = True
        DBOS(config=DBOSConfig(
            name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
            executor_id=f"cloudhelm-hub-{baseline.installation_id}", system_database_engine=system_engine,
            dbos_system_schema=DBOS_SCHEMA, run_migrations=False,
            serializer=DBOSPortableJSONSerializer(), use_listen_notify=True,
            max_executor_threads=runtime.MAX_EXECUTOR_THREADS, sys_db_polling_concurrency=1,
            enable_otlp=False, enable_patching=False,
            log_level="CRITICAL", console_log_level="CRITICAL",
        ))
        register_task_workflows(application)
        queues = ("control", "orchestration")
        DBOS.listen_queues(queues)
        DBOS.launch()
        for queue in queues:
            DBOS.register_queue(queue, worker_concurrency=1, global_concurrency=1,
                                polling_interval_sec=1.0)
        if not stop.is_set():
            runtime.emit_status("ready", installation_id=baseline.installation_id,
                                application_name=APPLICATION_NAME, application_version=APPLICATION_VERSION,
                                pid=os.getpid())
            stop.wait()
        runtime.emit_status("shutdown_requested")
        result = 0
    except Exception:
        runtime.emit_status("failed", reason="task_control_worker_start_or_run_failed")
    finally:
        try:
            if attempted:
                DBOS.destroy(destroy_registry=True, workflow_completion_timeout_sec=5)
        except Exception:
            runtime.emit_status("failed", reason="task_control_worker_shutdown_failed")
            result = 1
        finally:
            if client is not None:
                client.destroy()
            if system_engine is not None:
                system_engine.dispose()
            if pools is not None:
                pools.dispose()
    return result


def main():
    if sys.argv[1:] == ["--task-control-worker"]:
        return _task_control_worker_main()
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--development", action="store_true")
    mode.add_argument("--input-set")
    parser.add_argument("--storage-id", required=True)
    parser.add_argument("--storage-revision", required=True)
    parser.add_argument("--port", type=int, default=55441)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = {"method_revision": METHOD_REVISION,
              "method_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "started_at_utc": datetime.now(UTC).isoformat(), "status": "failed",
              "complete_scope": False, "human_acceptance": None,
              "product_acceptance": False, "protocol_fixture_classification": PROTOCOL_CLASSIFICATION,
              "mode": "development_worktree" if args.development else "fixed_input_set",
              "scenarios": CASE_NAMES,
              "scope": "real Workspace and Build accepted intents across Task completion and cancellation",
              "support_scope": "one WSL Ubuntu-24.04 local controlled development fixture"}
    before = None
    try:
        before = fixed_inputs(args.input_set)
        report["input_before"] = _public_input(before)
        run(args, report)
        report["status"] = "passed"
    except EngineeringCheckFailure as failure:
        report.update(status="failed", failure_code=str(failure))
    except DatabaseFixtureError:
        report.update(status="failed", failure_code="engineering_task_control_database_fixture_failed")
    except Exception as failure:
        report.update(status="failed", failure_code="engineering_task_control_method_failed",
                      failure_type=type(failure).__name__)
        report["failure_location"] = [{"file": Path(item.filename).name, "line": item.lineno,
                                       "function": item.name}
                                      for item in traceback.extract_tb(failure.__traceback__)[-6:]]
    finally:
        if before is not None:
            try:
                after = fixed_inputs(args.input_set)
                report["input_after"] = _public_input(after)
                report["public_inputs_unchanged"] = before == after
                require(before == after, "engineering_task_control_input_changed_during_run")
            except Exception:
                report.update(status="failed", failure_code="engineering_task_control_input_postcheck_failed",
                              public_inputs_unchanged=False)
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8", newline="\n") as output:
                output.write(encoded)
        except OSError:
            report.update(status="failed", failure_code="engineering_task_control_report_not_saved")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
