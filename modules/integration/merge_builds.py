"""Bind builds and source evidence to the current immutable integration attempt."""

import time

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import read_task
from modules.collaboration.records import reference_key
from modules.collaboration.tables import task_inputs
from modules.integration.merge_records import entry_for_attempt, read_attempt
from modules.projects.source_tables import project_git_sources
from modules.sync.tables import event_log
from packages.contracts.p1.workspace_git import content_digest
from packages.contracts.p1.workspace_records import workspace_metadata_digest


def integration_candidate(connection, task, candidate_id):
    attempt_id = connection.scalar(select(event_log.c.event_id).where(
        event_log.c.project_id == task["project_id"], event_log.c.event_type == "integration.prepared",
        event_log.c.payload["snapshot"]["candidate_id"].astext == candidate_id,
    ))
    attempt = read_attempt(connection, attempt_id) if attempt_id is not None else None
    if attempt is None or attempt.snapshot is None:
        raise TaskBoundaryError("integration_candidate_not_found")
    verify_integration_snapshot(connection, task, attempt.snapshot)
    return attempt.snapshot


def verify_integration_snapshot(connection, task, snapshot):
    attempt = read_attempt(connection, snapshot.freeze_operation_id)
    if attempt is None or attempt.state != "prepared" or attempt.snapshot != snapshot:
        raise TaskBoundaryError("integration_candidate_not_current")
    entry = entry_for_attempt(connection, attempt.attempt_id)
    source = entry.source
    current_input = connection.scalar(select(task_inputs.c.input_set_key).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    ))
    current_source = connection.execute(select(project_git_sources).where(
        project_git_sources.c.project_id == task["project_id"],
    )).mappings().one_or_none()
    suffix = content_digest(attempt.attempt_id.encode("utf-8"))[7:]
    if (entry.state not in {"awaiting_evidence", "applying", "merged"}
            or task["state"] != "active" or task["ordinary_progress_closed"]
            or task["cancel_requested_at"] is not None or task["input_status"] != "valid"
            or entry.project_id != task["project_id"] or entry.task_id != task["task_id"]
            or entry.control_revision != task["control_revision"]
            or entry.input_validity_revision != task["input_validity_revision"]
            or current_input != reference_key(task["project_id"], entry.source_input_set_ref)
            or attempt.project_id != entry.project_id or attempt.task_id != entry.task_id
            or attempt.entry_id != entry.entry_id or entry.attempt_id != attempt.attempt_id
            or not attempt.attempt_id.startswith("merge-attempt-")
            or snapshot.freeze_operation_id != attempt.attempt_id
            or snapshot.candidate_id != "integration-candidate-" + suffix
            or snapshot.storage_id != "candidate-" + suffix
            or snapshot.parent_commit != attempt.base_commit
            or attempt.candidate_commit != entry.candidate.candidate_commit
            or snapshot.binding != entry.candidate.binding
            or snapshot.binding.project_id != task["project_id"] or snapshot.binding.task_id != task["task_id"]
            or source.project_id != task["project_id"] or source.kind != "managed_bare" or source.source_prefix
            or source.source_id != snapshot.binding.source_id
            or source.source_revision != snapshot.binding.source_revision
            or current_source is None or current_source["source_json"] != source.model_dump(mode="json")
            or current_source["source_digest"] != workspace_metadata_digest(source)):
        raise TaskBoundaryError("integration_candidate_not_current")
    return attempt, entry


def read_integration_bytes(runtime, storage, record):
    from modules.workspaces.git_objects import _OPERATION_SECONDS, _read_object, read_commit_files
    from modules.workspaces.safe_paths import WorkspaceFileError
    from packages.contracts.p1.workspace_git import MAX_FILE_BYTES, WorkspaceManifest, manifest_bytes

    candidate = record.fixed_inputs.candidate
    with UnitOfWork(runtime.control_engine) as uow:
        task = read_task(uow.connection, record.task_id)
        _, entry = verify_integration_snapshot(uow.connection, task, candidate)
        if (record.project_id != task["project_id"]
                or record.control_revision != task["control_revision"]
                or record.input_validity_revision != task["input_validity_revision"]
                or record.fixed_inputs.source_input_set_ref != entry.source_input_set_ref):
            raise TaskBoundaryError("integration_build_input_stale")
    with runtime._git(storage, record.project_id) as git:
        with git.integration_repository(entry.source) as metadata:
            deadline = time.monotonic() + _OPERATION_SECONDS
            _, files = read_commit_files(metadata, candidate.candidate_commit, "", deadline)
            try:
                WorkspaceManifest(files=files)
            except ValueError:
                raise WorkspaceFileError("git_source_paths_unsupported") from None
            if content_digest(manifest_bytes(files)) != candidate.manifest_digest:
                raise WorkspaceFileError("build_candidate_content_mismatch")
            contents = {item.path: _read_object(metadata, "blob", item.blob_id, MAX_FILE_BYTES, deadline)
                        for item in files}
            if any(len(contents[item.path]) != item.size_bytes
                   or content_digest(contents[item.path]) != item.content_digest for item in files):
                raise WorkspaceFileError("build_candidate_content_mismatch")
            return contents
