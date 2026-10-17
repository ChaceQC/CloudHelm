"""One real Git/file candidate check with read-only local Docker observation."""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from modules.workspaces import candidate_content, candidate_freeze, candidate_store, file_journal
from modules.workspaces.candidate_freeze import CandidateFreezeController
from modules.workspaces.candidate_store import CandidateStore
from modules.workspaces.candidate_writers import process_start_ticks
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.git_objects import GitObjectStore, managed_repository_slot
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at, read_regular
from modules.workspaces.workfiles import WorkfileStore
from packages.contracts.p1.workspace_candidates import (
    CandidateFreezeSpec, RegisteredWorkspaceReader, WorkspaceWriterScope,
)
from packages.contracts.p1.workspace_git import (
    RegisteredGitSource, WorkspaceBinding, WorkspaceMutationSpec, WorkspaceReadSpec, content_digest,
)
from scripts.p1.check_workspace_git import _commit, _git, _tree


def reject(checks, label, code, call):
    try:
        call()
    except WorkspaceFileError as error:
        assert error.code == code, (label, error.code)
    else:
        raise AssertionError(label + ": rejection missing")
    checks.append(label)


def _readonly_fixture_checks(root, files, initial, controller, binding, scopes, checks):
    source = str(files / initial.storage_id / "files")
    unknown = {"id": "a" * 64, "status": "created", "pid": 0, "privileged": False, "devices": [],
               "cap_add": [], "pid_mode": "", "operation": "reader", "scope": "reader", "method": "fixture",
               "mounts": [{"Type": "bind", "Source": source, "Destination": "/workspace", "RW": True}]}
    boundary = PrivateRoot(files)

    def attempt():
        with boundary.exclusive() as stored:
            with directory_at(stored, initial.storage_id + "/files") as live:
                with controller.freeze(stored, live, binding, "writers"):
                    pass

    try:
        with patch.object(candidate_freeze, "_inventory", return_value=(unknown,)):
            reject(checks, "unknown-container-writer", "workspace_unknown_writer", attempt)
            unknown["mounts"][0]["RW"] = False
            reject(checks, "unregistered-readonly-container", "workspace_unknown_writer", attempt)
            original = scopes["writers"]
            scopes["writers"] = original.model_copy(update={"readers": (RegisteredWorkspaceReader(
                container_id="a" * 64, operation_id="different", scope="reader", method="fixture"),)})
            reject(checks, "reader-label-mismatch", "workspace_reader_mount_mismatch", attempt)
            scopes["writers"] = original
    finally:
        boundary.close()


def check(root, object_format, checks):
    repositories, files = root / "repositories", root / "workfiles"
    repositories.mkdir(mode=0o700)
    files.mkdir(mode=0o700)
    source = RegisteredGitSource(project_id="project", source_id="source", source_revision=1, kind="managed_bare",
                                 target_branch="refs/heads/main", object_format=object_format, access_mode="read_write")
    repository = repositories / managed_repository_slot(source)
    _git(repository, "init", "--bare", "--initial-branch=main", "--template=", "--object-format=" + object_format)
    parent = _commit(repository, _tree(repository, {"README.md": ("100644", b"original\n"),
                                                   "run.sh": ("100755", b"#!/bin/sh\nexit 0\n")}))
    _git(repository, "update-ref", "refs/heads/main", parent)
    git = GitObjectStore(repositories)
    git.register_source(source)
    binding = WorkspaceBinding(workspace_id="workspace", project_id="project", task_id="task", work_item_id="item",
                               owner_user_id="owner", source_id="source", source_revision=1, base_commit=parent,
                               workspace_revision=1, write_generation=1)
    initial_store = WorkfileStore(files, git, lambda _: binding)
    initial = initial_store.materialize(binding, "materialize")
    mutations, operations, scopes = {}, {}, {}
    service = WorkspaceFileService(files, git, lambda key: mutations[key])
    controller = CandidateFreezeController(lambda key: scopes[key])
    store = CandidateStore(files, git, lambda key: operations[key], controller)

    def current(version):
        value = binding.model_copy(update={"workspace_revision": version})
        mutations["read"] = WorkspaceReadSpec(binding=value, materialization_operation_id="materialize")
        status = service.status("read")
        return value, status

    def change(operation_id, version, data):
        value, status = current(version)
        mutations[operation_id] = WorkspaceMutationSpec(
            binding=value, materialization_operation_id="materialize", action="write", path="README.md", content=data,
            expected_manifest_digest=status.current_manifest_digest,
            expected_file=next(entry for entry in status.files if entry.path == "README.md"),
        )
        return service.apply(operation_id)

    def freeze_spec(operation_id, version, candidate_id):
        value, status = current(version)
        operations[operation_id] = CandidateFreezeSpec(
            binding=value, materialization_operation_id="materialize", candidate_id=candidate_id,
            expected_manifest_digest=status.current_manifest_digest, runtime_scope_id="writers",
        )
        scopes["writers"] = WorkspaceWriterScope(scope_id="writers", binding=value, service_instance_id="file-service",
                                                service_pid=os.getpid(), service_start_ticks=process_start_ticks(os.getpid()))
        return operations[operation_id]

    try:
        change("edit", 1, b"candidate bytes\n")
        original = freeze_spec("freeze", 2, "candidate-one")
        assert store.query("freeze").state == "not_found"
        captured = store.capture("freeze")
        assert captured == store.capture("freeze") == store.query("freeze").receipt
        assert captured.snapshot.parent_commit == parent
        assert _git(repository, "rev-parse", "refs/heads/main") == parent
        actual = _git(repository, "cat-file", "commit", captured.snapshot.candidate_commit)
        assert "parent " + parent in actual
        checks.extend([object_format + ":independent-commit-and-parent", "target-branch-unchanged", "stable-query-and-replay"])
        with store.open_candidate("freeze") as (receipt, saved):
            assert read_regular(saved, "README.md", 128) == b"candidate bytes\n"
            assert not os.fstat(saved).st_mode & 0o222
            assert receipt == captured
        change("later", 2, b"development continued\n")
        with store.open_candidate("freeze") as (receipt, saved):
            assert read_regular(saved, "README.md", 128) == b"candidate bytes\n"
        assert store.query("freeze").receipt == captured
        checks.append("resumed-development-candidate-unchanged")
        operations["freeze"] = original.model_copy(update={"candidate_id": "different"})
        reject(checks, "same-operation-different-digest", "candidate_request_digest_conflict", lambda: store.capture("freeze"))
        operations["freeze"] = original
        freeze_spec("collision", 3, "candidate-one")
        reject(checks, "candidate-identity-conflict", "candidate_identity_conflict", lambda: store.capture("collision"))
        spec = freeze_spec("bad-manifest", 3, "candidate-bad")
        operations["bad-manifest"] = spec.model_copy(update={"expected_manifest_digest": content_digest(b"wrong")})
        reject(checks, "manifest-must-match", "candidate_manifest_conflict", lambda: store.capture("bad-manifest"))
        if object_format == "sha1":
            _readonly_fixture_checks(root, files, initial, controller, spec.binding, scopes, checks)
            freeze_spec("lost", 3, "candidate-lost")
            rename = os.rename

            def lost_response(*arguments, **keywords):
                rename(*arguments, **keywords)
                if arguments[0].startswith("stage-"):
                    raise OSError("synthetic lost publication response")

            with patch.object(candidate_store.os, "rename", side_effect=lost_response):
                reject(checks, "lost-publication-response", "candidate_capture_unconfirmed", lambda: store.capture("lost"))
            reconciled = store.query("lost")
            assert reconciled.state == "captured" and store.capture("lost") == reconciled.receipt
            checks.append("lost-response-reconciled-without-recapture")
            freeze_spec("interrupted", 3, "candidate-interrupted")
            with patch.object(candidate_content, "copy_files", side_effect=OSError("synthetic interruption")):
                reject(checks, "interrupted-capture", "candidate_capture_unconfirmed", lambda: store.capture("interrupted"))
            assert store.query("interrupted").state == "unknown"
            reject(checks, "unknown-not-blindly-replayed", "candidate_capture_pending_reconciliation", lambda: store.capture("interrupted"))
            freeze_spec("late-writer", 3, "candidate-late-writer")
            validate, calls = controller.validate, [0]

            def changed_writer(*arguments):
                calls[0] += 1
                if calls[0] == 2:
                    raise WorkspaceFileError("workspace_unknown_writer")
                return validate(*arguments)

            with patch.object(controller, "validate", side_effect=changed_writer):
                reject(checks, "writer-change-before-seal", "workspace_unknown_writer", lambda: store.capture("late-writer"))
            assert store.query("late-writer").state == "unknown"
            checks.append("failed-writer-check-cannot-reconcile-as-captured")
            freeze_spec("pending-files", 3, "candidate-pending-files")
            with patch.object(file_journal, "publish", side_effect=OSError("synthetic pending file write")):
                reject(checks, "pending-file-fixture", "workspace_file_unconfirmed", lambda: change("pending-write", 3, b"pending\n"))
            reject(checks, "pending-file-write-blocks-candidate", "workspace_file_pending_reconciliation", lambda: store.capture("pending-files"))
        store._resolver = lambda _: (_ for _ in ()).throw(LookupError())
        reject(checks, "query-rechecks-current-authority", "workspace_operation_unregistered", lambda: store.query("freeze"))
    finally:
        store.close()
        service.close()
        initial_store.close()
        git.close()


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="cloudhelm-candidate-") as temporary:
        root = Path(temporary)
        try:
            for object_format in ("sha1", "sha256"):
                case = root / object_format
                case.mkdir(mode=0o700)
                check(case, object_format, checks)
        finally:
            for directory, _, names in os.walk(root):
                os.chmod(directory, 0o700)
                for name in names:
                    os.chmod(Path(directory) / name, 0o600)
    print(json.dumps({"method": "p1-workspace-candidates-r1", "status": "passed",
                      "scope": "development_git_files_and_readonly_docker_inventory",
                      "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                      "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
