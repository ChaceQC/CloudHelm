"""One real-file development check for controlled single-file operations."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from modules.workspaces import file_journal
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.git_objects import GitObjectStore, managed_repository_slot
from modules.workspaces.safe_paths import WorkspaceFileError
from modules.workspaces.workfiles import WorkfileStore
from packages.contracts.p1.workspace_git import (
    RegisteredGitSource, WorkspaceBinding, WorkspaceMutationSpec, WorkspaceReadSpec,
)
from scripts.p1.check_workspace_git import _commit, _git, _tree


def reject(checks, name, code, call):
    try:
        call()
    except WorkspaceFileError as error:
        assert error.code == code, (name, error.code)
    else:
        raise AssertionError(name + ": rejection missing")
    checks.append(name)


def check(root, checks):
    repositories, files = root / "repositories", root / "workfiles"
    repositories.mkdir(mode=0o700)
    files.mkdir(mode=0o700)
    source = RegisteredGitSource(project_id="project", source_id="source", source_revision=1, kind="managed_bare",
                                 target_branch="refs/heads/main", object_format="sha1", access_mode="read_write")
    repository = repositories / managed_repository_slot(source)
    _git(repository, "init", "--bare", "--initial-branch=main", "--template=")
    commit = _commit(repository, _tree(repository, {"README.md": ("100644", b"original\n"), "remove.txt": ("100644", b"remove me\n")}))
    _git(repository, "update-ref", "refs/heads/main", commit)
    git = GitObjectStore(repositories)
    git.register_source(source)
    binding = WorkspaceBinding(workspace_id="workspace", project_id="project", task_id="task", work_item_id="item",
                               owner_user_id="owner", source_id="source", source_revision=1, base_commit=commit,
                               workspace_revision=1, write_generation=1)
    initial_store = WorkfileStore(files, git, lambda _: binding)
    initial = initial_store.materialize(binding, "materialize")
    operations, calls = {}, {}

    def resolve(operation_id):
        calls[operation_id] = calls.get(operation_id, 0) + 1
        if operation_id == "revoked" and calls[operation_id] == 3:
            raise LookupError
        return operations[operation_id]

    service = WorkspaceFileService(files, git, resolve)

    def view(version):
        operations["read"] = WorkspaceReadSpec(binding=binding.model_copy(update={"workspace_revision": version}), materialization_operation_id="materialize")
        return service.status("read")

    def mutation(operation_id, version, path, content=None, action="write"):
        current = view(version)
        operations[operation_id] = WorkspaceMutationSpec(
            binding=operations["read"].binding, materialization_operation_id="materialize", action=action, path=path,
            expected_file=next((entry for entry in current.files if entry.path == path), None),
            expected_manifest_digest=current.current_manifest_digest, content=content,
        )

    try:
        assert view(1).change_count == 0
        mutation("write", 1, "README.md", b"edited\n")
        first = service.apply("write")
        assert first.outcome == "applied" and service.apply("write") == service.query("write").receipt == first
        assert view(2).changes[0].kind == "modified" and "+edited" in service.diff("read", "README.md").patch
        assert initial_store.query(binding, "materialize") == initial
        checks.extend(["write-status-diff", "original-materialization-unchanged", "replay-original-result"])
        mutation("stale", 1, "README.md", b"stale\n")
        reject(checks, "stale-revision", "workspace_revision_stale", lambda: service.apply("stale"))
        operations["write"] = operations["write"].model_copy(update={"content": b"different request\n"})
        reject(checks, "same-id-different-digest", "workspace_request_digest_conflict", lambda: service.apply("write"))
        mutation("delete", 2, "remove.txt", action="delete")
        assert service.apply("delete").outcome == "applied"
        assert not (files / initial.storage_id / "files/remove.txt").exists()
        assert any(change.kind == "deleted" for change in view(3).changes)
        assert "-remove me" in service.diff("read", "remove.txt").patch
        checks.append("delete-and-diff")
        mutation("lost", 3, "README.md", b"recovered publication\n")
        record = file_journal.write_record

        def lost_receipt(directory, name, value):
            if name == "receipt.json":
                raise OSError("synthetic lost receipt")
            return record(directory, name, value)

        with patch.object(file_journal, "write_record", side_effect=lost_receipt):
            reject(checks, "lost-write-receipt", "workspace_file_unconfirmed", lambda: service.apply("lost"))
        assert service.query("lost").state == "applied"
        assert service.apply("lost") == service.query("lost").receipt
        mutation("revoked", 4, "README.md", b"must not publish\n")
        reject(checks, "prewrite-revoked", "workspace_operation_unregistered", lambda: service.apply("revoked"))
        assert service.query("revoked").state == "not_applied"
        assert (files / initial.storage_id / "files/README.md").read_bytes() == b"recovered publication\n"
        mutation("conflict", 4, "README.md", b"conflict\n")
        operations["conflict"] = operations["conflict"].model_copy(update={"expected_file": first.before_file})
        reject(checks, "wrong-file-digest", "workspace_file_conflict", lambda: service.apply("conflict"))
        mutation("generation", 4, "README.md", b"generation\n")
        operations["generation"] = operations["generation"].model_copy(update={"binding": binding.model_copy(update={"workspace_revision": 4, "write_generation": 0})})
        reject(checks, "stale-generation", "workspace_generation_stale", lambda: service.apply("generation"))
        mutation("binary", 4, "binary.dat", b"\0\xff\x01")
        assert service.apply("binary").outcome == "applied"
        view(5)
        assert service.diff("read", "binary.dat").binary
        checks.append("create-and-binary-diff")
        reject(checks, "path-boundary", "workspace_path_invalid", lambda: service.diff("read", "../outside"))
        linked = files / initial.storage_id / "files/linked"
        linked.symlink_to(root / "outside")
        reject(checks, "symlink-refused", "storage_not_service_owned", lambda: service.status("read"))
        linked.unlink()
        mutation("pending", 5, "README.md", b"not attempted\n")
        with patch.object(file_journal, "publish", side_effect=OSError("synthetic interrupted publication")):
            reject(checks, "interrupted-write", "workspace_file_unconfirmed", lambda: service.apply("pending"))
        assert service.query("pending").state == "pending" and service.query("pending").target_state == "old"
        mutation("blocked", 5, "README.md", b"blocked\n")
        reject(checks, "pending-blocks-new-write", "workspace_file_pending_reconciliation", lambda: service.apply("blocked"))
        assert view(5).unresolved_operations == 1
        return initial.manifest_digest, view(5).current_manifest_digest
    finally:
        service.close()
        initial_store.close()
        git.close()


def main():
    start, checks = datetime.now(UTC).isoformat(), []
    with tempfile.TemporaryDirectory(prefix="cloudhelm-file-operations-") as directory:
        initial, current = check(Path(directory), checks)
    print(json.dumps({"method_revision": "p1-file-operations-r1", "input_kind": "development_worktree",
                      "started_at": start, "finished_at": datetime.now(UTC).isoformat(), "checks": checks,
                      "check_count": len(checks), "initial_manifest_digest": initial, "current_manifest_digest": current,
                      "result": "passed"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
