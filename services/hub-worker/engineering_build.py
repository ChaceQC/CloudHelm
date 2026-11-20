"""Delivery composition: fixed candidate bytes, Runner proof, then one short UoW."""

import importlib
import json
from contextlib import ExitStack, closing, contextmanager, nullcontext

from database.commands import get_by_id
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.delivery.commands import resolve_build_operation_in_uow
from modules.delivery.queries import build_view, read_build_execution, read_build_intent
from modules.delivery.receipts import (
    register_verified_build_content, register_verified_build_observation, verify_build_content, verify_build_observation,
)
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.integration.merge_builds import read_integration_bytes
from modules.agent_runtime.source_context import safe_context_text
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular
from modules.workspaces.workspace_views import observe
from packages.contracts.p1.build_records import BuildArtifactLocator
from packages.contracts.p1.task_results import TaskCommandResult
from packages.contracts.p1.workspace_git import MAX_FILE_BYTES, content_digest


def _record(runtime, operation_id, *, control_command_id=None, stop=False):
    if stop and control_command_id is None:
        raise IdentityError("authorization_binding_mismatch")
    with UnitOfWork(runtime.control_engine) as uow:
        _, record = read_build_intent(uow.connection, operation_id)
        actor = actor_for_command(uow, control_command_id or record.command_id)
        task, _ = lock_task_access(uow, actor, record.task_id, "resource.read")
        if control_command_id is not None:
            command = get_by_id(uow.connection, control_command_id)
            if task["cancel_requested_at"] is None or command.status_code != 202 or command.envelope.action != "task.cancel":
                raise IdentityError("authorization_binding_mismatch")
            result = TaskCommandResult.model_validate(command.result)
            original = (result.outcome == "cancellation_requested" and task["cancel_command_id"] == control_command_id)
            if (result.task_id != record.task_id or result.control_purpose != "cancellation"
                    or not (original or result.outcome == "reconciliation_requested")):
                raise IdentityError("authorization_binding_mismatch")
        resource = AuthoritativeResource(record.project_id, "operation", operation_id, task_id=record.task_id)
        authorize_current(uow, actor, resource, "operation.query")
        if stop:
            authorize_current(uow, actor, resource, "operation.stop")
        return record, actor


def _candidate_bytes(runtime, storage, record):
    candidate = record.fixed_inputs.candidate
    if candidate.candidate_id.startswith("integration-candidate-"):
        return read_integration_bytes(runtime, storage, record)
    return _workspace_candidate_bytes(runtime, storage, candidate)


def _workspace_candidate_bytes(runtime, storage, candidate):
    intent = runtime._intent(candidate.freeze_operation_id)
    with runtime._git(storage, candidate.binding.project_id) as git:
        store = runtime._candidate_store(storage, git, intent, reconciliation=True)
        try:
            with store.open_candidate(candidate.freeze_operation_id) as (receipt, files):
                if receipt.snapshot != candidate:
                    raise WorkspaceFileError("build_candidate_receipt_mismatch")
                observation = observe(files)
                if observation.digest != candidate.manifest_digest:
                    raise WorkspaceFileError("build_candidate_content_mismatch")
                contents = {entry.path: read_regular(files, entry.path, MAX_FILE_BYTES)
                            for entry in observation.manifest.files}
                if any(content_digest(contents[entry.path]) != entry.content_digest
                       or len(contents[entry.path]) != entry.size_bytes for entry in observation.manifest.files):
                    raise WorkspaceFileError("build_candidate_content_mismatch")
                return contents
        finally:
            store.close()


def definition_for_snapshot(runtime, snapshot, acceptance_ref):
    definitions = importlib.import_module("services.dev-runner.engineering_definition")
    with runtime.registry.admit(0) as storage:
        files = _workspace_candidate_bytes(runtime, storage, snapshot)
        return definitions.definition_for_candidate(files, acceptance_ref)


def read_build_result(runtime, record, *, log_role, log_offset, max_bytes):
    """Read the original private journal only; querying never creates a runner."""
    runner_module = importlib.import_module("services.dev-runner.engineering_build_runner")
    with runtime.registry.pin() as storage, closing(PrivateRoot(storage.archive_root)) as archive, ExitStack() as stack:
        if not exists_at(archive.fd, "build-operations"):
            return {"available": False, "failure": None, "log": None}
        operations = stack.enter_context(directory_at(archive.fd, "build-operations"))
        if not exists_at(operations, record.command_id):
            return {"available": False, "failure": None, "log": None}
        root = stack.enter_context(directory_at(operations, record.command_id))
        intent = runner_module.read_attempt_intent(root)
        if intent is None:
            return {"available": False, "failure": None, "log": None}
        if intent.record != record:
            raise WorkspaceFileError("build_result_binding_mismatch")
        result = json.loads(read_regular(root, "result.json", 1024**2)) if exists_at(root, "result.json") else {}
        report = json.loads(read_regular(root, log_role + ".json", 1024**2)) if exists_at(root, log_role + ".json") else {}
        failures = [{key: safe_context_text(item[key]) for key in ("category", "diagnostic", "detail")
                     if key in item} for item in report.get("failures", [])]
        texts, captures = [], []
        if exists_at(root, log_role):
            logs = stack.enter_context(directory_at(root, log_role))
            for phase, name in (("build", "build-output"), ("dependencies", "dependency-output")):
                filename = name + ".json"
                if not exists_at(logs, filename):
                    continue
                value = json.loads(read_regular(logs, filename, 512 * 1024))
                texts.append("[" + phase + "]\n" + value.pop("text"))
                captures.append({"phase": phase, **value})
        raw = "\n".join(texts).encode("utf-8")
        if log_offset > len(raw):
            raise WorkspaceFileError("build_log_offset_out_of_range")
        # Offsets address retained UTF-8 bytes; finish at a character boundary.
        start = log_offset
        if start < len(raw) and raw[start] & 0xC0 == 0x80:
            raise WorkspaceFileError("build_log_offset_not_utf8_boundary")
        text = raw[start:start + max_bytes].decode("utf-8", errors="ignore")
        end = start + len(text.encode("utf-8"))
        return {"available": True, "failure": result.get("failure"), "failures": failures,
                "log": {"role": log_role, "available": bool(captures), "text": text,
                        "offset": start, "next_offset": end if end < len(raw) else None,
                        "total_bytes": len(raw), "captures": captures}}


def execute_build(runtime, operation_id):
    runner_module = importlib.import_module("services.dev-runner.engineering_build_runner")
    record, _ = _record(runtime, operation_id)
    with runtime.registry.pin() as storage:
        def gate():
            storage.observe()
            with UnitOfWork(runtime.control_engine) as uow:
                current = resolve_build_operation_in_uow(uow, operation_id)
            if current != record:
                raise WorkspaceFileError("build_operation_binding_changed")

        with closing(runner_module.ControlledBuildRunner(storage, record, gate)) as runner:
            group = runtime.resources.build(record)
            prepared, frontend_bases = None, None
            if not runner.exists():
                if group is not None:
                    raise WorkspaceFileError("engineering_build_acceptance_unconfirmed")
                prepared, frontend_bases = _prepare_build(runtime, storage, record, gate, runner_module)
                gate()
                group = runtime.resources.reserve_build(record, storage)
            with group.context() if group is not None else nullcontext():
                inspection = runner.submit(prepared, frontend_bases,
                    start_resource=lambda: runtime.resources.start_build(group, gate))
                return _register_inspection(runtime, record, runner, group, inspection, finish=True)


def _prepare_build(runtime, storage, record, gate, runner_module):
    if storage.observe().allocatable_bytes < 2 * 1024**3:
        development_storage = importlib.import_module("services.dev-runner.development_storage")
        raise development_storage.DevelopmentStorageError("storage_capacity_unavailable")
    gate()

    def registered(previous, observation):
        with UnitOfWork(runtime.control_engine) as uow:
            _, original = read_build_intent(uow.connection, previous.operation_id)
            if original != previous:
                return False
            head = read_build_execution(uow.connection, previous)
            return head is not None and head.observation == observation

    runner_module.check_previous_builds(storage, record, registered)
    definitions = importlib.import_module("services.dev-runner.engineering_definition")
    definition = record.fixed_inputs.definition
    prepared = definitions.prepare_build(_candidate_bytes(runtime, storage, record),
                                         definition.acceptance_assets_ref)
    if prepared.definition != definition:
        raise runner_module.ProbeFailure("engineering_build_definition_mismatch")
    images = importlib.import_module("services.dev-runner.frontend_images")
    return prepared, images.verify_frontend_layouts()


def _register_inspection(runtime, record, runner, group, inspection, *, actor=None, finish=False):
    receipt = inspection and (runner.recovered_stop_receipt or inspection.resource_receipt)
    physically_closed = receipt is not None and receipt.state in {"closed_unstarted", "stopped"}
    if physically_closed:
        group.dispatcher.reconcile(group.request.resources.identity.reservation_id, receipt=receipt)
    if inspection is None or inspection.observation is None:
        with UnitOfWork(runtime.control_engine) as uow:
            return build_view(uow.connection, record).model_dump(mode="json")
    operation_id = record.operation_id
    physical = verify_build_observation(operation_id, runner)
    predecessor = None
    if inspection.predecessor is not None:
        predecessor = verify_build_observation(operation_id, runner, predecessor=True)
    observation = physical.observation
    content = None
    if len(observation.artifacts) == 3:
        content = verify_build_content(record, runner.store, tuple(
            BuildArtifactLocator(role=item.role, storage_id=item.storage_id) for item in observation.artifacts
        ))
    if (finish and not group.stopped and not physically_closed and inspection.stop_requested_at is None
            and observation.closure not in {"unknown", "running"}):
        group.stop()  # Whole daemon/descendants close before the business receipt.
    with UnitOfWork(runtime.engine) as uow:
        if predecessor is not None:
            register_verified_build_observation(uow, operation_id, predecessor, actor=actor)
        if content is not None:
            register_verified_build_content(uow, operation_id, content, actor=actor)
        register_verified_build_observation(uow, operation_id, physical, actor=actor)
        if runtime.client is not None:
            from modules.agent_runtime.operations import notify_operation_in_uow

            notify_operation_in_uow(uow, runtime.client, operation_id,
                engineering_registration=runtime.registry.registration,
                preview_installation=runtime.preview_installation)
        return build_view(uow.connection, record).model_dump(mode="json")


@contextmanager
def _original_runner(runtime, record):
    runner_module = importlib.import_module("services.dev-runner.engineering_build_runner")
    with runtime.registry.pin() as storage:
        group = runtime.resources.build(record)
        with (
            group.context() if group is not None else nullcontext(),
            closing(runner_module.ControlledBuildRunner(storage, record, storage.observe)) as runner,
        ):
            yield runner, group


def inspect_build(runtime, operation_id, *, control_command_id=None):
    record, _ = _record(runtime, operation_id, control_command_id=control_command_id)
    with _original_runner(runtime, record) as (runner, _):
        return runner.inspect()


def request_build_stop(runtime, operation_id, *, executor_generation, control_command_id):
    record, actor = _record(runtime, operation_id, control_command_id=control_command_id, stop=True)
    with _original_runner(runtime, record) as (runner, group):
        inspection = runner.request_stop(operation_id, executor_generation)
        if inspection is not None:
            _register_inspection(runtime, record, runner, group, inspection, actor=actor)
        return inspection
