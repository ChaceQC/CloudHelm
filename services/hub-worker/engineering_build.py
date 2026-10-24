"""Delivery composition: fixed candidate bytes, Runner proof, then one short UoW."""

import importlib

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.delivery.commands import resolve_build_operation_in_uow
from modules.delivery.queries import build_view, read_build_execution, read_build_intent
from modules.delivery.receipts import (
    register_verified_build_content, register_verified_build_observation, verify_build_content, verify_build_observation,
)
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.workspaces.safe_paths import WorkspaceFileError, read_regular
from modules.workspaces.workspace_views import observe
from packages.contracts.p1.build_records import BuildArtifactLocator
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
    intent = runtime._intent(candidate.freeze_operation_id)
    with runtime._git(storage, record.project_id) as git:
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
            return build_view(uow.connection, record).model_dump(mode="json")
    finally:
        runner.close()
