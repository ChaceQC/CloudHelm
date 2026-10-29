"""Reconcile preview intents against the existing Runner and resource ledger."""

import hashlib
import importlib
import json
import re
from datetime import datetime, timedelta
from uuid import uuid4

from dbos import DBOS, WorkflowSerializationFormat
from sqlalchemy import and_, func, or_, select, update

from database.uow import UnitOfWork
from modules.artifacts.content_store import ArtifactStore
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.guards import check_task_revisions, read_task, require_ordinary_progress
from modules.delivery.queries import build_view, read_build_intent
from modules.identity.actors import actor_for_command
from modules.integration.candidates import _read, _ref
from modules.integration.human_test_records import current_verification, read_session
from modules.workspaces.development_queries import read_development_environment, read_development_operation_record
from modules.workspaces.development_tables import workspace_development_environment_operations as development_operations
from modules.workspaces.operations import current_engineering_input, read_workspace_row
from modules.workspaces.preview_access import _environment
from modules.workspaces.preview_access_tables import preview_environments
from modules.workspaces.preview_environment_tables import preview_environment_intents as intents
from modules.workspaces.preview_environments import PreviewEnvironmentApplication, _intent, save_environment
from modules.workspaces.preview_profiles import fixed_preview_inputs
from modules.workflow.engineering_enqueuers import preview_environment_enqueuer
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION
from packages.contracts.p1.workspace_development_requests import DisposeWorkspaceDevelopmentRequest
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p2.previews import PreviewEnvironmentRecord, PreviewUpstream


def _load(runtime, operation_id):
    with UnitOfWork(runtime.control_engine) as uow:
        intent = _intent(uow.connection, operation_id)
        record = _environment(uow.connection, intent["environment_id"])
        binding = uow.connection.execute(select(workflow_bindings).where(
            workflow_bindings.c.workflow_id == "engineering-" + operation_id)).mappings().one()
        payload = intent["request_json"]
        keys = ("environment_id", "purpose", "candidate_id", "session_id", "prepare_operation_id",
                "control_revision", "input_validity_revision") if intent["action"] == "prepare" else ()
        original = {key: payload[key] for key in keys}
        digest = "sha256:" + hashlib.sha256(json.dumps(original, sort_keys=True).encode("utf-8")).hexdigest()
        expected_operation = (record.environment_id if intent["action"] == "prepare" else "preview-stop-" +
                              hashlib.sha256(record.environment_id.encode()).hexdigest()[:32])
        if (intent["action"] not in {"prepare", "stop"} or binding["command_id"] != intent["command_id"]
                or operation_id != expected_operation or binding["advance_revision"] > record.revision
                or binding["business_kind"] != "workspace" or binding["business_id"] != record.environment_id
                or binding["workflow_name"] != "workspaces.preview.v1"
                or binding["process_type"] != "workspaces.preview.v1" or binding["queue_name"] != "engineering"
                or binding["request_digest"] != digest
                or (intent["action"] == "prepare" and (
                    original["environment_id"] != record.environment_id or original["purpose"] != record.purpose
                    or original["candidate_id"] != record.candidate_id
                    or original["session_id"] != record.human_test_session_id))):
            raise ValueError("preview_handoff_identity_mismatch")
        return dict(intent), record


def _candidate(runtime, record):
    with UnitOfWork(runtime.control_engine) as uow:
        task = read_task(uow.connection, record.task_id)
        candidate = _read(uow.connection, task, record.candidate_id)
        _, build = read_build_intent(uow.connection, candidate.build_operation_id)
        return candidate, build_view(uow.connection, build)


def _gate(runtime, intent, record, *, starting=True):
    """A fresh grant and fixed inputs precede each new physical side effect."""
    with UnitOfWork(runtime.control_engine) as uow:
        actor = actor_for_command(uow, intent["command_id"])
        task, _ = lock_task_access(uow, actor, record.task_id, "operation.request" if starting else "resource.read")
        current = _environment(uow.connection, record.environment_id, lock=True)
        payload = _intent(uow.connection, intent["operation_id"])["request_json"]
        if task["state"] == "completed" and current.purpose == "human_test":
            check_task_revisions(task, expected_version=task["version"],
                expected_control_revision=payload["control_revision"],
                expected_input_validity_revision=payload["input_validity_revision"])
        else:
            task = require_ordinary_progress(uow.connection, record.task_id, expected_version=task["version"],
                expected_control_revision=payload["control_revision"],
                expected_input_validity_revision=payload["input_validity_revision"])
        now = uow.connection.scalar(select(func.clock_timestamp()))
        if (current.state not in ({"preparing"} if starting else {"preparing", "ready"})
                or current.revision != record.revision or now >= current.expires_at):
            raise ValueError("preview_preparation_no_longer_current")
        if current.purpose == "development":
            _, request, row, _, _ = read_development_operation_record(uow.connection, payload["prepare_operation_id"])
            if (row["task_id"] != current.task_id or row["workspace_id"] != current.workspace_id
                    or request.action != "prepare" or not request.preview):
                raise ValueError("preview_development_binding_changed")
            current_engineering_input(uow.connection, task, request.input_set_ref)
            return
        deadline = payload.get("resource_deadline")
        if deadline is not None and now >= datetime.fromisoformat(deadline) - timedelta(hours=6):
            raise ValueError("preview_preparation_deadline_exceeded")
        candidate = _read(uow.connection, task, current.candidate_id)
        if (_ref("candidate", candidate.candidate_id, candidate.schema_revision, "integration", candidate)
                != current.candidate_ref or candidate.source_input_set_ref != current.input_set_ref
                or candidate.control_revision != task["control_revision"] and task["state"] != "completed"
                or candidate.input_validity_revision != task["input_validity_revision"]):
            raise ValueError("preview_candidate_not_current")
        current_engineering_input(uow.connection, task, candidate.source_input_set_ref)
        profile = fixed_preview_inputs(uow.connection, candidate)
        if current.purpose == "human_test":
            session = read_session(uow.connection, current.human_test_session_id)
            if (session.state not in {"preparing", "awaiting_human", "testing"}
                    or session.round_id != session.session_id or current.test_round != 1
                    or session.candidate_id != candidate.candidate_id or session.candidate_ref != current.candidate_ref
                    or (session.test_config_ref, session.dataset_ref) != profile):
                raise ValueError("preview_human_round_not_current")
            current_verification(uow.connection, task, session)


def _save(runtime, operation_id, observation, reason, *, stopped=False):
    with UnitOfWork(runtime.engine) as uow:
        initial = _intent(uow.connection, operation_id)
        read_task(uow.connection, _environment(uow.connection, initial["environment_id"]).task_id, for_update=True)
        record = _environment(uow.connection, initial["environment_id"], lock=True)
        row = uow.connection.execute(select(intents).where(intents.c.operation_id == operation_id).with_for_update()).mappings().one()
        payload = dict(row["request_json"])
        payload["observation"] = observation
        if row["action"] == "prepare" and observation.get("ready") and "physical_ready_at" not in payload:
            payload["physical_ready_at"] = uow.connection.scalar(select(func.clock_timestamp())).isoformat()
        uow.connection.execute(update(intents).where(intents.c.operation_id == operation_id).values(
            request_json=payload, reason=reason, updated_at=func.clock_timestamp()))
        changes = {}
        if observation.get("reservation_id"):
            changes["resource_reservation_id"] = observation["reservation_id"]
        if row["action"] == "prepare" and record.state in {"preparing", "ready"} and observation.get("ready"):
            changes["actual_revision"] = observation["actual_revision"]
        if row["action"] == "prepare" and record.state == "ready" and not observation.get("ready"):
            from modules.workspaces.preview_access import revoke_environment_in_uow

            revoke_environment_in_uow(uow, record.environment_id)
            changes.update(state="preparing", revision=record.revision + 1)
        if stopped and row["action"] == "stop" and record.state == "stopping":
            changes["state"] = "stopped"
        if changes:
            save_environment(uow.connection, PreviewEnvironmentRecord.model_validate(
                record.model_dump() | changes))
    return {"operation_id": operation_id, "state": "stopped" if stopped else "unknown", "code": reason}


def _candidate_operation(runtime, intent, record, *, stopping):
    candidate, build = _candidate(runtime, record)
    operation_id = record.environment_id
    runner_type = importlib.import_module("services.dev-runner.candidate_preview").CandidatePreview
    with runtime.registry.admit(0) as storage:
        directory = storage.admission.directory / (
            "candidate-preview-" + hashlib.sha256(operation_id.encode()).hexdigest()[:32])
        existing = directory.exists()
        binding = runtime.resources.binding(key=operation_id, task_id=record.task_id,
            command_id=intent["command_id"], deadline=record.expires_at, storage=storage,
            start=False, preview=True)
        deadline = None if binding is None else binding.request.expires_at_utc
        if binding is not None and not stopping:
            recorded = intent["request_json"].get("resource_deadline")
            if recorded is None or datetime.fromisoformat(recorded) != deadline:
                raise ValueError("preview_resource_deadline_mismatch")
        if not existing and not stopping:
            if binding is None:
                with UnitOfWork(runtime.engine) as uow:
                    read_task(uow.connection, record.task_id, for_update=True)
                    current_record = _environment(uow.connection, record.environment_id, lock=True)
                    if current_record.state != "preparing" or current_record.revision != record.revision:
                        raise ValueError("preview_preparation_no_longer_current")
                    current = _intent(uow.connection, intent["operation_id"])
                    deadline = uow.connection.scalar(select(func.clock_timestamp())) + timedelta(hours=6, minutes=10)
                    payload = dict(current["request_json"]) | {"resource_deadline": deadline.isoformat()}
                    uow.connection.execute(update(intents).where(intents.c.operation_id == intent["operation_id"]).values(
                        request_json=payload, updated_at=func.clock_timestamp()))
            else:
                _save(runtime, intent["operation_id"], {"ready": False, "state": "preparing",
                    "reservation_id": binding.request.resources.identity.reservation_id, "targets": {},
                    "resource_deadline": deadline.isoformat()}, "preview_physical_unconfirmed")
            _gate(runtime, intent, record)
            binding = runtime.resources.binding(key=operation_id, task_id=record.task_id,
                command_id=intent["command_id"], deadline=deadline, storage=storage, start=True, preview=True)
        if binding is None:
            if stopping and not existing:
                return {"ready": False, "state": "stopped", "reservation_id": None, "targets": {}}, True
            raise ValueError("preview_resource_binding_unavailable")
        reservation_id = binding.request.resources.identity.reservation_id
        if stopping and not existing:
            if not binding.stopped:
                binding.stop()
            return {"ready": False, "state": "stopped", "reservation_id": reservation_id, "targets": {}}, True
        if not stopping and not existing:
            _save(runtime, intent["operation_id"], {"ready": False, "state": "preparing",
                "reservation_id": reservation_id, "targets": {}}, "preview_physical_unconfirmed")
        with binding.context(), ArtifactStore(storage.archive_root / "artifacts") as store:
            runner = runner_type(operation_id=operation_id, candidate=candidate, build=build,
                store=store, admission=storage.admission,
                start_gate=None if stopping else lambda: _gate(runtime, intent, record))
            if stopping:
                observed = runner.stop()
                if observed["state"] != "stopped":
                    raise ValueError("preview_physical_stop_unconfirmed")
                if not binding.stopped:
                    binding.stop()
                return {"ready": False, "state": "stopped", "reservation_id": reservation_id, "targets": {}}, True
            observed = runner.observe() if existing else runner.prepare()
        ready = observed["state"] == "ready"
        targets = {}
        if ready:
            for service, value in observed["targets"].items():
                upstream = PreviewUpstream(service=service, host=value["ipv4"], port=value["port"])
                targets[service] = {"host": upstream.host, "port": upstream.port}
        return {"ready": ready, "state": observed["state"], "route_supported": False,
                "actual_revision": build.record.fixed_inputs.candidate.candidate_commit,
                "reservation_id": reservation_id, "targets": targets,
                "resource_deadline": deadline.isoformat(), "data_revision": observed.get("data_revision")}, False


def _development_observation(runtime, intent, record):
    _gate(runtime, intent, record, starting=False)
    adapter = importlib.import_module("services.dev-runner.preview_development").DevelopmentPreview(
        runtime._development, runtime.resources)
    value = adapter.observe(intent["request_json"]["prepare_operation_id"])
    resource = runtime.resources._existing(value["reservation_id"]) if value["reservation_id"] else None
    targets = {}
    if value["target"] is not None:
        target = value["target"]
        upstream = PreviewUpstream(service="backend", host=target["address"], port=target["port"])
        targets["backend"] = {"host": upstream.host, "port": upstream.port}
    return {"ready": value["ready"], "state": "ready" if value["ready"] else "preparing",
            "route_supported": value["route_supported"], "actual_revision": str(value["workspace_revision"])
            if value["workspace_revision"] is not None else None, "workspace_revision": value["workspace_revision"],
            "reservation_id": value["reservation_id"], "targets": targets,
            "resource_deadline": resource[0].expires_at_utc.isoformat() if resource else None,
            "data_revision": value["data_revision"]}


def _dispose_development(runtime, intent, record):
    with UnitOfWork(runtime.control_engine) as uow:
        original = _intent(uow.connection, record.environment_id)
        _, client_request, row, _, _ = read_development_operation_record(
            uow.connection, original["request_json"]["prepare_operation_id"])
        environment = read_development_environment(uow.connection, row["environment_id"])
        actor = actor_for_command(uow, intent["command_id"])
        task = read_task(uow.connection, record.task_id)
        workspace = read_workspace_row(uow.connection, record.workspace_id)
        binding = WorkspaceBinding.model_validate(workspace["binding_json"])
        pending = uow.connection.execute(select(development_operations).where(
            development_operations.c.environment_id == environment["environment_id"],
            development_operations.c.action == "dispose").order_by(
            development_operations.c.accepted_environment_revision.desc()).limit(1)).mappings().one_or_none()
        disposed = environment["state"] == "disposed" and environment["stop_fact_json"] is not None
    if disposed:
        access = runtime._development._access(row["operation_id"], reconciliation=True)
        with runtime.resources.admitted() as storage:
            resource = runtime.resources.environment(access, storage)
        if (resource is None and record.resource_reservation_id is not None
                or resource is not None and not resource.stopped):
            raise ValueError("preview_development_release_unconfirmed")
        return {"ready": False, "state": "stopped", "reservation_id": record.resource_reservation_id,
                "targets": {}}, True
    payload = intent["request_json"]
    dispose_id = payload.get("dispose_operation_id")
    if dispose_id is not None:
        status = runtime.client.retrieve_workflow("engineering-" + dispose_id).get_status().status
        if status not in {"ENQUEUED", "PENDING", "DELAYED"}:
            runtime.development_environment(dispose_id)
        return {"ready": False, "state": "stopping", "reservation_id": record.resource_reservation_id,
                "targets": {}}, False
    request_data = payload.get("dispose_request")
    if pending is not None and pending["operation_state"] in {"pending", "unknown"} and request_data is None:
        status = runtime.client.retrieve_workflow("engineering-" + pending["operation_id"]).get_status().status
        if status not in {"ENQUEUED", "PENDING", "DELAYED"}:
            runtime.development_environment(pending["operation_id"])
        return {"ready": False, "state": "stopping", "reservation_id": record.resource_reservation_id,
                "targets": {}}, False
    attempt = payload.get("dispose_attempt", 0)
    if request_data is None:
        request = DisposeWorkspaceDevelopmentRequest(expected_version=task["version"],
            expected_control_revision=task["control_revision"],
            expected_input_validity_revision=task["input_validity_revision"], input_set_ref=client_request.input_set_ref,
            expected_workspace_revision=binding.workspace_revision, expected_write_generation=binding.write_generation,
            expected_environment_revision=environment["environment_revision"],
            expected_data_revision=environment["data_revision"], expected_data_generation=environment["data_generation"])
        request_data = request.model_dump(mode="json")
        with UnitOfWork(runtime.engine) as uow:
            current = _intent(uow.connection, intent["operation_id"])
            stored = dict(current["request_json"]) | {"dispose_request": request_data, "dispose_attempt": attempt}
            uow.connection.execute(update(intents).where(intents.c.operation_id == intent["operation_id"]).values(
                request_json=stored, updated_at=func.clock_timestamp()))
    request = DisposeWorkspaceDevelopmentRequest.model_validate(request_data)
    key = "preview-dispose-" + hashlib.sha256(record.environment_id.encode()).hexdigest()[:32] + "-" + str(attempt)
    result = runtime.development.control(actor, environment["environment_id"], request, key).body
    with UnitOfWork(runtime.engine) as uow:
        current = _intent(uow.connection, intent["operation_id"])
        stored = dict(current["request_json"])
        if result.outcome == "accepted":
            stored["dispose_operation_id"] = result.operation_id
        else:
            stored.pop("dispose_request", None)
            stored["dispose_attempt"] = attempt + 1
        uow.connection.execute(update(intents).where(intents.c.operation_id == intent["operation_id"]).values(
            request_json=stored, reason=result.code, updated_at=func.clock_timestamp()))
    return {"ready": False, "state": "stopping", "reservation_id": record.resource_reservation_id,
            "targets": {}}, False


def execute_preview(runtime, operation_id):
    intent, record = _load(runtime, operation_id)
    if intent["action"] == "prepare" and record.state not in {"preparing", "ready"}:
        return {"operation_id": operation_id, "state": record.state, "code": "preview_preparation_closed"}
    if intent["action"] == "stop" and record.state != "stopping":
        return {"operation_id": operation_id, "state": record.state, "code": "preview_stop_closed"}
    try:
        if record.purpose == "development":
            observation, stopped = (_dispose_development(runtime, intent, record) if intent["action"] == "stop"
                                    else (_development_observation(runtime, intent, record), False))
        else:
            observation, stopped = _candidate_operation(runtime, intent, record, stopping=intent["action"] == "stop")
        reason = ("preview_stopped" if stopped else "preview_route_unconfigured" if observation["ready"]
                  else "preview_physical_unconfirmed")
        return _save(runtime, operation_id, observation, reason, stopped=stopped)
    except Exception as error:
        code = getattr(error, "category", None) or getattr(error, "code", None)
        if code is None and isinstance(error, ValueError):
            value = str(error)
            if value.startswith(("engineering_", "preview_", "resource_", "workspace_")):
                code = value
        if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,159}", code) is None:
            code = "preview_physical_unconfirmed"
        return _save(runtime, operation_id, {"ready": False, "state": "unknown",
            "reservation_id": record.resource_reservation_id, "targets": {}}, code)


def maintain_previews(runtime):
    from modules.integration.human_test_wiring import human_test_application

    previews = PreviewEnvironmentApplication(runtime.engine, runtime.control_engine,
        enqueue=preview_environment_enqueuer(runtime.client), load_installation=False)
    human_test_application(runtime.engine, runtime.control_engine, previews).maintenance()
    with UnitOfWork(runtime.control_engine) as uow:
        rows = uow.connection.execute(select(intents.c.operation_id, intents.c.environment_id, intents.c.request_json).join(
            preview_environments, preview_environments.c.environment_id == intents.c.environment_id).where(or_(
            and_(preview_environments.c.state == "preparing", intents.c.action == "prepare"),
            and_(preview_environments.c.state == "stopping", intents.c.action == "stop"),
            and_(preview_environments.c.state == "ready", intents.c.action == "prepare"),
        )).order_by(intents.c.updated_at, intents.c.operation_id).limit(16)).all()
    for operation_id, environment_id, snapshot in rows:
        previous = snapshot.get("retry_workflow_id", "engineering-" + operation_id)
        status = DBOS.get_workflow_status(previous)
        with UnitOfWork(runtime.engine) as uow:
            initial = _environment(uow.connection, environment_id)
            task = read_task(uow.connection, initial.task_id, for_update=True)
            record = _environment(uow.connection, environment_id, lock=True)
            row = uow.connection.execute(select(intents).where(intents.c.operation_id == operation_id).with_for_update()).mappings().one()
            at = uow.connection.scalar(select(func.clock_timestamp()))
            if record.state in {"preparing", "ready"} and at >= record.expires_at:
                previews.stop_in_uow(uow, record, row["command_id"])
                continue
            payload = row["request_json"]
            if (record.state in {"preparing", "ready"} and row["action"] == "prepare" and (
                    task["cancel_requested_at"] is not None or task["input_status"] != "valid"
                    or task["input_validity_revision"] != payload["input_validity_revision"]
                    or task["control_revision"] != payload["control_revision"] and task["state"] != "completed"
                    or task["state"] == "completed" and record.purpose != "human_test")):
                previews.stop_in_uow(uow, record, row["command_id"])
                continue
            deadline = row["request_json"].get("resource_deadline")
            if (record.state == "preparing" and record.resource_reservation_id is not None
                    and deadline is not None and "physical_ready_at" not in row["request_json"]
                    and at >= datetime.fromisoformat(deadline) - timedelta(hours=6)):
                previews.stop_in_uow(uow, record, row["command_id"])
                continue
            uow.connection.execute(update(intents).where(intents.c.operation_id == operation_id).values(updated_at=at))
            if (row["action"] == "prepare" and record.state not in {"preparing", "ready"}
                    or row["action"] == "stop" and record.state != "stopping"):
                continue
            payload = dict(row["request_json"])
            if previous != payload.get("retry_workflow_id", "engineering-" + operation_id):
                continue
            if status is None:
                uow.connection.execute(update(intents).where(intents.c.operation_id == operation_id).values(
                    reason="preview_workflow_missing"))
                continue
            if status.status in {"ENQUEUED", "PENDING", "DELAYED"}:
                continue
            retry_id = "preview-retry-" + uuid4().hex
            runtime.client.enqueue_in_transaction(uow.connection, {
                "workflow_name": "workspaces.preview.v1", "queue_name": "engineering", "workflow_id": retry_id,
                "workflow_id_reuse_policy": "return-existing", "app_version": APPLICATION_VERSION,
                "application_name": APPLICATION_NAME, "serialization_type": WorkflowSerializationFormat.PORTABLE,
            }, operation_id)
            payload["retry_workflow_id"] = retry_id
            uow.connection.execute(update(intents).where(intents.c.operation_id == operation_id).values(
                request_json=payload, updated_at=at))
    return {"examined": len(rows)}
