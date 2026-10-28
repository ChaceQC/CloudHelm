"""Delivery composition: fixed candidate bytes, Runner proof, then one short UoW."""

import importlib
import json
from contextlib import ExitStack, closing

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.delivery.commands import resolve_build_operation_in_uow
from modules.delivery.queries import build_view, read_build_execution, read_build_intent
from modules.delivery.receipts import (
    register_verified_build_content, register_verified_build_observation, verify_build_content, verify_build_observation,
)
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.integration.merge_builds import read_integration_bytes
from modules.agent_runtime.source_context import safe_context_text
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular
from modules.workspaces.workspace_views import observe
from packages.contracts.p1.build_records import BuildArtifactLocator, BuildRunRecord
from packages.contracts.p1.workspace_git import MAX_FILE_BYTES, content_digest


def _record(runtime, operation_id, *, reconciliation):
    with UnitOfWork(runtime.control_engine) as uow:
        if not reconciliation:
            return resolve_build_operation_in_uow(uow, operation_id)
        _, record = read_build_intent(uow.connection, operation_id)
        actor = actor_for_command(uow, record.command_id)
        lock_task_access(uow, actor, record.task_id, "operation.request")
        authorize_current(uow, actor, AuthoritativeResource(
            record.project_id, "operation", operation_id, task_id=record.task_id,
        ), "operation.query")
        return record


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
    with runtime.registry.admit(0) as storage, closing(PrivateRoot(storage.archive_root)) as archive, ExitStack() as stack:
        if not exists_at(archive.fd, "build-operations"):
            return {"available": False, "failure": None, "log": None}
        operations = stack.enter_context(directory_at(archive.fd, "build-operations"))
        if not exists_at(operations, record.command_id):
            return {"available": False, "failure": None, "log": None}
        root = stack.enter_context(directory_at(operations, record.command_id))
        if not exists_at(root, "intent.json"):
            return {"available": False, "failure": None, "log": None}
        intent = BuildRunRecord.model_validate_json(read_regular(root, "intent.json", 1024**2))
        if intent != record:
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
    with runtime.registry.admit(2 * 1024**3) as storage:
        record = _record(runtime, operation_id, reconciliation=True)

        def gate():
            storage.observe()
            if _record(runtime, operation_id, reconciliation=False) != record:
                raise WorkspaceFileError("build_operation_binding_changed")

        with runtime.resources.build(record, storage, gate) as group:
            return _execute_admitted(runtime, operation_id, record, storage, gate, runner_module, group)


def _execute_admitted(runtime, operation_id, record, storage, gate, runner_module, group):
    runner = runner_module.ControlledBuildRunner(storage, record, gate)
    try:
        if not runner.exists():
            gate()
            runner.execute(_candidate_bytes(runtime, storage, record))
        with UnitOfWork(runtime.control_engine) as uow:
            previous = read_build_execution(uow.connection, record)
            runner.previous_observation_id = None if previous is None else previous.observation.observation_id
        physical = verify_build_observation(operation_id, runner)
        observation = physical.observation
        content = None
        if len(observation.artifacts) == 3:
            content = verify_build_content(record, runner.store, tuple(
                BuildArtifactLocator(role=item.role, storage_id=item.storage_id) for item in observation.artifacts
            ))
        if group is not None and not group.stopped and observation.closure != "unknown":
            group.stop()  # Whole daemon/descendants close before the business receipt.
        with UnitOfWork(runtime.engine) as uow:
            if content is not None:
                register_verified_build_content(uow, operation_id, content)
            register_verified_build_observation(uow, operation_id, physical)
            if runtime.client is not None:
                from modules.agent_runtime.operations import notify_operation_in_uow

                notify_operation_in_uow(uow, runtime.client, operation_id)
            return build_view(uow.connection, record).model_dump(mode="json")
    finally:
        runner.close()
