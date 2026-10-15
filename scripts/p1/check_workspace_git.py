"""Narrow Linux development check for registered raw-Git and initial file views."""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from modules.workspaces.git_objects import GitObjectStore, managed_repository_slot
from modules.workspaces.git_process import run_git
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, read_regular, write_new_file
from modules.workspaces.workfiles import WorkfileStore
from packages.contracts.p1.workspace_git import (
    RegisteredGitSource, WorkspaceBinding, content_digest,
)

_FIXTURE_ENV = {
    "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    "HOME": "/nonexistent", "XDG_CONFIG_HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "CloudHelm fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "CloudHelm fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-10-15T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-15T00:00:00Z",
}


def _git(repository: Path, *arguments: str, data: bytes | None = None) -> str:
    result = subprocess.run(
        ["/usr/bin/git", f"--git-dir={repository}", *arguments], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_FIXTURE_ENV,
        cwd="/", timeout=10, check=False,
    )
    if result.returncode:
        raise RuntimeError("fixture_git_failed")
    return result.stdout.decode("utf-8").strip()


def _tree(repository: Path, files: dict) -> str:
    entries = []
    for name, value in sorted(files.items()):
        if isinstance(value, dict):
            mode, oid = "40000", _tree(repository, value)
        else:
            mode, data = value
            oid = _git(repository, "hash-object", "-w", "--stdin", data=data)
        entries.append(mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid))
    return _git(repository, "hash-object", "--literally", "-t", "tree", "-w", "--stdin",
                data=b"".join(entries))


def _commit(repository: Path, tree: str, parent: str | None = None) -> str:
    arguments = ("-p", parent) if parent else ()
    return _git(repository, "commit-tree", tree, *arguments, data=b"controlled fixture\n")


def _reject(checks: list[str], label: str, code: str, call) -> None:
    try:
        call()
    except WorkspaceFileError as error:
        if error.code != code:
            raise AssertionError(f"{label}: expected {code}, got {error.code}") from None
    else:
        raise AssertionError(f"{label}: rejection missing")
    checks.append(label)


def _safe_paths(root: Path, checks: list[str]) -> None:
    boundary = root / "boundary"
    boundary.mkdir(mode=0o700)
    outside = root / "outside.txt"
    outside.write_bytes(b"outside unchanged")
    (boundary / "linked").symlink_to(outside)
    (boundary / "linked-dir").symlink_to(root, target_is_directory=True)
    os.mkfifo(boundary / "fifo", 0o600)
    os.link(outside, boundary / "hardlink")
    storage = PrivateRoot(boundary)
    try:
        with storage.exclusive() as directory:
            for path in ("../outside.txt", "/absolute", ".git/config", "aux.txt", "a\\b", "a:b"):
                _reject(checks, f"path:{path}", "workspace_path_invalid",
                        lambda path=path: write_new_file(directory, path, b"forbidden"))
            for name in ("linked", "fifo"):
                _reject(checks, f"special:{name}", "storage_not_service_owned",
                        lambda name=name: read_regular(directory, name, 1024))
            _reject(checks, "symlink-directory", "storage_path_unavailable",
                    lambda: read_regular(directory, "linked-dir/outside.txt", 1024))
            _reject(checks, "hardlink", "storage_hardlink_forbidden",
                    lambda: read_regular(directory, "hardlink", 1024))
            write_new_file(directory, "nested/valid.txt", b"UTF-8: \xe4\xb8\xad\xe6\x96\x87")
            assert read_regular(directory, "nested/valid.txt", 1024).startswith(b"UTF-8:")
        assert outside.read_bytes() == b"outside unchanged"
        checks.append("fd-relative-safe-read-write")
    finally:
        storage.close()


def _source(root: Path, object_format: str, checks: list[str]) -> None:
    repositories, views = root / "repositories", root / "views"
    repositories.mkdir(mode=0o700)
    views.mkdir(mode=0o700)
    source = RegisteredGitSource(
        project_id="project-fixture", source_id="source-fixture", source_revision=1,
        kind="managed_bare", target_branch="refs/heads/main", object_format=object_format,
        access_mode="read_write",
    )
    repository = repositories / managed_repository_slot(source)
    subprocess.run(["/usr/bin/git", "init", "--bare", "--initial-branch=main", "--template=",
                    f"--object-format={object_format}", str(repository)],
                   env=_FIXTURE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=10, check=True)
    repository.chmod(0o700)
    files = {"README.md": ("100644", b"original\r\n"),
             "src": {"main.py": ("100644", b"print('fixture')\n")},
             "run.sh": ("100755", b"#!/bin/sh\nexit 0\n"),
             ".gitattributes": ("100644", b"* text=auto\n*.png -text -diff -merge\n")}
    first = _commit(repository, _tree(repository, files))
    latest = _commit(repository, _tree(repository, {"new.txt": ("100644", b"later")}), first)
    _git(repository, "update-ref", "refs/heads/main", latest)
    git = GitObjectStore(repositories)
    binding = WorkspaceBinding(
        workspace_id="workspace-one", project_id=source.project_id, task_id="task-fixture",
        work_item_id="item-fixture", owner_user_id="owner-fixture", source_id=source.source_id,
        source_revision=1, base_commit=first, workspace_revision=1, write_generation=1,
    )
    operations, calls = {"materialize-one": binding}, [0]

    def resolve(operation_id):
        if operation_id == "revoked":
            calls[0] += 1
            if calls[0] >= 3:
                raise LookupError
        return operations[operation_id]

    store = WorkfileStore(views, git, resolve)
    try:
        assert git.register_source(source) == git.register_source(source)
        _reject(checks, "source-replacement", "git_source_already_registered", lambda: git.register_source(
            source.model_copy(update={"source_id": "replacement"})))
        _reject(checks, "external-source", "git_external_source_unsupported", lambda: git.register_source(
            source.model_copy(update={"kind": "external"})))
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "invalid", "GIT_DIR": "/untrusted"}):
            tree = git.inspect_commit(source, first)
        assert tree.commit == first and len(tree.files) == 4 and tree.manifest_digest.startswith("sha256:")
        with git.open_commit(source, first) as (tree, reader):
            entry = next(item for item in tree.files if item.path == "README.md")
            assert reader(entry) == b"original\r\n"
        _reject(checks, "expired-object-reader", "git_file_scope_mismatch", lambda: reader(entry))
        outsider = _commit(repository, _tree(repository, {"other.txt": ("100644", b"orphan")}))
        _reject(checks, "outside-target", "git_commit_outside_target", lambda: git.inspect_commit(source, outsider))
        _reject(checks, "non-exact-commit", "git_object_format_mismatch", lambda: git.inspect_commit(source, "HEAD"))
        receipt = store.materialize(binding, "materialize-one")
        assert receipt == store.materialize(binding, "materialize-one") == store.query(binding, "materialize-one")
        location = views / receipt.storage_id
        assert not (location / "files/.git").exists()
        assert os.stat(location / "files/run.sh").st_mode & 0o777 == 0o755
        (location / "files/README.md").write_bytes(b"mutable edit")
        assert store.query(binding, "materialize-one") == receipt
        second = binding.model_copy(update={"workspace_id": "workspace-two"})
        operations["materialize-two"] = second
        independent = store.materialize(second, "materialize-two")
        original = views / independent.storage_id / "files/README.md"
        assert original.read_bytes() == b"original\r\n"
        assert original.stat().st_ino != (location / "files/README.md").stat().st_ino
        checks.extend(["precise-commit-and-clean-environment", "independent-workfiles-and-replay", "initial-receipt-is-not-live-evidence"])
        invalid = binding.model_copy(update={"base_commit": "HEAD"})
        _reject(checks, "query-invalid-binding", "workspace_binding_invalid", lambda: store.query(invalid, "materialize-one"))
        operations.pop("materialize-one")
        _reject(checks, "replay-revoked", "workspace_operation_unregistered", lambda: store.materialize(binding, "materialize-one"))
        operations["materialize-one"] = binding
        revoked = binding.model_copy(update={"workspace_id": "workspace-revoked"})
        operations["revoked"] = revoked
        before = set(views.iterdir())
        _reject(checks, "prepublish-revoked", "workspace_operation_unregistered", lambda: store.materialize(revoked, "revoked"))
        assert set(views.iterdir()) == before
        saved_receipt, saved_manifest = (location / "receipt.json").read_bytes(), (location / "manifest.json").read_bytes()
        changed = json.loads(saved_receipt)
        changed["file_count"] += 1
        (location / "receipt.json").write_text(json.dumps(changed), encoding="utf-8")
        _reject(checks, "receipt-count-mismatch", "workspace_receipt_mismatch", lambda: store.query(binding, "materialize-one"))
        changed = json.loads(saved_manifest)
        changed["files"][0]["path"] = "../escape"
        invalid_manifest = json.dumps(changed).encode("utf-8")
        changed = json.loads(saved_receipt)
        changed["manifest_digest"] = content_digest(invalid_manifest)
        (location / "manifest.json").write_bytes(invalid_manifest)
        (location / "receipt.json").write_text(json.dumps(changed), encoding="utf-8")
        _reject(checks, "manifest-unsafe-path", "workspace_manifest_invalid", lambda: store.query(binding, "materialize-one"))
        (location / "receipt.json").write_bytes(saved_receipt)
        (location / "manifest.json").write_bytes(saved_manifest)
        unsafe = [({"link": ("120000", b"/outside")}, "git_entry_type_unsupported"),
                  ({"..": ("100644", b"escape")}, "git_path_unsupported"),
                  ({".gitmodules": ("100644", b"unsupported")}, "git_extension_unsupported"),
                  ({"large.dat": ("100644", b"version https://git-lfs.github.com/spec/v1\n")}, "git_lfs_unsupported"),
                  ({".gitattributes": ("100644", b"* filter=untrusted\n")}, "git_attributes_unsupported"),
                  ({"README": ("100644", b"one"), "readme": ("100644", b"two")}, "git_source_paths_unsupported")]
        for index, (bad_files, error) in enumerate(unsafe):
            commit = _commit(repository, _tree(repository, bad_files), latest)
            _git(repository, "update-ref", "refs/heads/main", commit)
            _reject(checks, f"unsupported-tree-{index}", error, lambda: git.inspect_commit(source, commit))
        _git(repository, "update-ref", "refs/heads/alternate", latest)
        _git(repository, "symbolic-ref", "refs/heads/main", "refs/heads/alternate")
        _reject(checks, "symbolic-target", "git_target_branch_symbolic", lambda: git.inspect_commit(source, first))
        _git(repository, "update-ref", "--no-deref", "refs/heads/main", latest)
        config = (repository / "config").read_bytes()
        (repository / "config").write_bytes(config + b"\n[include]\npath=/nonexistent\n")
        _reject(checks, "dangerous-config", "git_config_unsupported", lambda: git.inspect_commit(source, first))
        (repository / "config").write_bytes(config)
        (repository / "hooks").mkdir()
        (repository / "hooks/pre-commit").write_bytes(b"#!/bin/sh\nexit 97\n")
        _reject(checks, "active-hook", "git_hooks_unsupported", lambda: git.inspect_commit(source, first))
        (repository / "hooks/pre-commit").unlink()
        private = PrivateRoot(repository)
        try:
            with private.exclusive() as directory:
                _reject(checks, "command-whitelist", "git_operation_unsupported", lambda: run_git(
                    directory, ("status",), limit=1024, deadline=time.monotonic() + 1))
        finally:
            private.close()
        _git(repository, "pack-refs", "--all", "--prune")
        assert git.inspect_commit(source, first).commit == first
        checks.append("packed-target-reference")
    finally:
        store.close()
        git.close()


def main() -> None:
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    checks = []
    with tempfile.TemporaryDirectory(prefix="cloudhelm-workspace-git-") as directory:
        root = Path(directory)
        _safe_paths(root, checks)
        for object_format in ("sha1", "sha256"):
            fixture = root / object_format
            fixture.mkdir(mode=0o700)
            _source(fixture, object_format, checks)
    print(json.dumps({
        "method_revision": "p1-workspace-git-r1", "input_kind": "development_worktree",
        "started_at": started, "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "platform": sys.platform, "python": sys.version.split()[0],
        "object_formats": ["sha1", "sha256"], "checks": checks, "check_count": len(checks),
        "result": "passed",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
